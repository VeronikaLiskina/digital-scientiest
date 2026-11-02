"""Publication lookup by explicit criteria, independent of answer generation."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.author import Author
from app.models.document_chunk import DocumentChunk
from app.models.keyword import Keyword
from app.models.publication import Publication
from app.models.topic import Topic
from app.services.publication_query_service import CATALOG_MAX_ITEMS, _normalize_question


@dataclass(frozen=True)
class PublicationSearch:
    topic: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    language: str = ""
    publication_type: str = ""
    count_only: bool = False
    with_descriptions: bool = False
    title: str = ""
    publication_ids: tuple[int, ...] | None = None


# One vocabulary for document references. A title lookup must not depend on
# the genre stored in the publication card (a collection can be tagged article).
DOCUMENT_NOUN = (
    r"(?:стат(?:ья|ью|ьи|ей)|публикаци\w*|книг\w*|сборник\w*|документ\w*|"
    r"материал\w*|работ[аыуе]|работ|обзор\w*|монографи\w*|диссертаци\w*|"
    r"отчет\w*|тезис\w*|труд\w*|патент\w*|исследовани\w*|"
    r"publications?|papers?|articles?|studies|books?|reviews?|collections?|"
    r"proceedings|documents?|reports?|patents?)"
)
TITLE_LOOKUP_ACTION = r"(?:найди(?:те)?|покажи(?:те)?|открой(?:те)?|есть\s+ли|ищу|find|show|open)"
TITLE_MARKER = r"(?:(?:с\s+названием|под\s+названием|по\s+названию|called|titled)\s+)?"
TITLE_LOOKUP_PREFIX = re.compile(
    rf"^(?:{TITLE_LOOKUP_ACTION}\s+)?(?:(?:мне|me|the|a)\s+)*"
    rf"(?:{DOCUMENT_NOUN}\s+)?{TITLE_MARKER}$"
)
TITLE_DESCRIPTION_PREFIX = re.compile(
    rf"^(?:расскажи(?:те)?\s+(?:о|об|про)|о\s+чем|describe|summari[sz]e|tell\s+me\s+about)\s+"
    rf"(?:(?:the|a)\s+)?(?:{DOCUMENT_NOUN}\s+)?{TITLE_MARKER}$"
)
UNQUOTED_TITLE_PREFIX = re.compile(
    rf"^(?:{TITLE_LOOKUP_ACTION}\s+)?(?:(?:мне|me|the|a)\s+)*"
    rf"{DOCUMENT_NOUN}\s+{TITLE_MARKER}"
)


@dataclass(frozen=True)
class DocumentReference:
    title: str
    catalog_request: bool


def extract_document_reference(question: str) -> DocumentReference | None:
    """Separate a quoted document title from the action/question around it."""
    text = _normalize_lookup(question)
    quoted = re.search(r'[«“„"]([^»”"«]+)[»”"]', text)
    if quoted is None:
        return None
    prefix = text[:quoted.start()].lstrip()
    suffix = text[quoted.end():].strip(" ,;:?.!")
    if not suffix and (TITLE_LOOKUP_PREFIX.fullmatch(prefix) or TITLE_DESCRIPTION_PREFIX.fullmatch(prefix)):
        return DocumentReference(quoted[1].strip(), catalog_request=True)
    # Content questions need retrieval within the selected document, rather
    # than a catalog card or an unrestricted search across unrelated articles.
    if re.search(rf"\b{DOCUMENT_NOUN}\b", prefix) or re.search(r"\b(?:в|из|in|from)\s*$", prefix):
        return DocumentReference(quoted[1].strip(), catalog_request=False)
    return None


def is_description_followup(question: str) -> bool:
    return bool(re.fullmatch(
        r"(?:а )?(?:о чем он[аи]?|чему они посвящены|расскажи о н(?:ей|ем|их)|"
        r"расскажи подробнее|подробнее|с описанием)", _normalize_lookup(question),
    ))


TYPE_PREFIXES = (
    ("стать", "article"), ("материалы конференц", "conference"),
    ("конференц", "conference"), ("отчет", "report"), ("книг", "book"),
    ("тезис", "thesis"), ("обзор", "review"), ("монограф", "monograph"),
    ("диссертац", "dissertation"),
)
TYPE_LABELS = {
    "article": "статья", "conference": "материалы конференции", "report": "отчет",
    "book": "книга", "thesis": "тезисы", "review": "обзор",
    "monograph": "монография", "dissertation": "диссертация",
}
NOUN = rf"(?:материалы\s+конференци\w*|статьям|{DOCUMENT_NOUN})"
LOOKUP = re.compile(
    rf"^(?:(?:покажи(?:те)?|найди(?:те)?|подбери(?:те)?|перечисли(?:те)?|список|каталог|какие|сколько|есть\s+ли)\s+"
    rf"(?:(?:мне|все|научные|загруженные)\s+)*|в\s+каких\s+|"
    rf"(?:find|show|list|select|how\s+many|which|what)\s+(?:(?:me|all|scientific)\s+)*)?(?P<noun>{NOUN})\b"
)
TOKEN = re.compile(r"[a-zа-я0-9]+", re.I)
STOPWORDS = {"и", "или", "о", "об", "по", "про", "в", "во", "на", "с", "со", "из", "для", "к", "от", "the", "of", "and", "on", "in"}


def _normalize_lookup(question: str) -> str:
    text = _normalize_question(question).strip(" ?!.;")
    text = re.sub(r"^(?:можешь|можете)(?:\s+ли)?\s+", "", text)
    text = re.sub(r"^(?:can|could)\s+you\s+", "", text)
    text = re.sub(r"\b(?:пожалуйста|please)\b[,]?", "", text).strip(" ,")
    text = re.sub(r"^(подобрать|найти|показать|перечислить)\b", lambda m: {
        "подобрать": "подбери", "найти": "найди", "показать": "покажи", "перечислить": "перечисли",
    }[m[1]], text)
    return " ".join(text.replace(",", " ").split())


def parse_publication_search(question: str, conversation: str | None = None) -> PublicationSearch | None:
    text = _normalize_lookup(question)
    previous = [line.removeprefix("Пользователь:").strip() for line in (conversation or "").splitlines()
                if line.startswith("Пользователь:")]
    inherited = None
    if previous:
        inherited = parse_publication_search(previous[-1], "\n".join(f"Пользователь: {q}" for q in previous[:-1]))
    if is_description_followup(question):
        return replace(inherited, with_descriptions=True, count_only=False) if inherited else None
    if re.fullmatch(r"(?:а )?(?:сколько (?:их|таких)|how many of them)", text):
        return replace(inherited, count_only=True, with_descriptions=False) if inherited else None
    # Elliptical follow-ups may refine an existing catalog selection. Never use
    # a previous scientific answer as an implicit catalog filter.
    followup = re.match(r"^(?:а\s+(?:только\s+)?|оставь\s+(?:только\s+)?|покажи\s+только\s+|only\s+)(.+)$", text)
    if followup and inherited:
        refined = _parse_search("публикации " + followup[1], question,
                                initial=replace(inherited, count_only=False, with_descriptions=False))
        return refined
    return _parse_search(text, question)


def _parse_search(text: str, original: str, *, initial: PublicationSearch | None = None) -> PublicationSearch | None:
    reference = extract_document_reference(original)
    if reference is not None:
        return PublicationSearch(title=reference.title, with_descriptions=True) if reference.catalog_request else None
    match = LOOKUP.match(text)
    if match is None:
        return None
    noun = match["noun"]
    rest = text[match.end():].strip()
    filters = initial or PublicationSearch(count_only=text.startswith(("сколько ", "how many ")))
    for prefix, value in TYPE_PREFIXES:
        if value != "article" and noun.startswith(prefix):
            filters = replace(filters, publication_type=value)
    if noun in {"book", "books", "review", "reviews"}:
        filters = replace(filters, publication_type=noun.rstrip("s"))
    # Plain "статьи" remains a generic catalog request, as in the existing UI.
    type_match = re.search(r"\b(?:типа|тип)\s+(материалы\s+конференци\w*|стать\w*|article|конференц\w*|conference|отчет\w*|report|книг\w*|book|тезис\w*|thesis|обзор\w*|review|монограф\w*|monograph|диссертац\w*|dissertation)\b", rest)
    if type_match:
        value = type_match[1]
        kind = next((kind for prefix, kind in TYPE_PREFIXES if value.startswith(prefix)), value)
        filters = replace(filters, publication_type=kind)
        rest = rest[:type_match.start()] + " " + rest[type_match.end():]
    language = re.search(r"\b(?:на\s+(русском|английском)(?:\s+языке)?|in\s+(russian|english))\b", rest)
    if language:
        filters = replace(filters, language="ru" if (language[1] or language[2]) in {"русском", "russian"} else "en")
        rest = rest[:language.start()] + " " + rest[language.end():]
    years = re.search(r"\b(?:(?:с|за|from|between)\s+)?((?:18|19|20)\d{2})\s*(?:[-–—]|по|до|to|and)\s*((?:18|19|20)\d{2})(?:\s*(?:годов|годы|года|год|гг?\.?))?", rest)
    if years:
        filters = replace(filters, year_from=int(years[1]), year_to=int(years[2]))
        rest = rest[:years.start()] + " " + rest[years.end():]
    else:
        year = re.search(r"\b(за|в|после|до|с|in|after|before|since)?\s*((?:18|19|20)\d{2})(?:\s*(?:году|года|год|г\.?))?\b", rest)
        if year:
            value = int(year[2])
            lower = None if year[1] in {"до", "before"} else value + (year[1] in {"после", "after"})
            upper = value - 1 if year[1] in {"до", "before"} else (None if year[1] in {"с", "после", "since", "after"} else value)
            filters = replace(filters, year_from=lower, year_to=upper)
            rest = rest[:year.start()] + " " + rest[year.end():]
    description = re.search(r"\b(?:с\s+(?:кратким\s+)?описанием|и\s+(?:кратко\s+)?(?:расскажи|расскажите)\s+о\s+(?:них|каждой))\b", rest)
    if description:
        filters = replace(filters, with_descriptions=True)
        rest = rest[:description.start()] + " " + rest[description.end():]
    author = re.search(r"\b(?:(?:по\s+)?автор(?:а|ов|у)?|написанные|написаны|by)\s+(.+?)(?=\s+(?:по|про|о|об|на тему|с описанием|about|on)\s+|$)", rest)
    if author:
        filters = replace(filters, author=author[1].strip(" ,;"))
        rest = rest[:author.start()] + " " + rest[author.end():]
    rest = re.sub(r"\b(?:в\s+(?:системе|базе(?:\s+данных)?|каталоге)|есть|имеются|находятся|загружены)\b", " ", rest)
    rest = " ".join(rest.split()).strip(" ,;")
    topic = re.match(r"^(?:по\s+(?:теме\s+)?|на\s+тему\s+|о\s+|об\s+|про\s+|about\s+|on\s+|посвящен\w*\s+|(?:где\s+)?упомина\w*\s+|с\s+ключев\w*\s+слов\w*\s+)(.+)$", rest)
    if topic:
        filters = replace(filters, topic=topic[1].strip(' «»".,;?!'))
    elif rest and re.fullmatch(r"[а-я]+(?:ов[ау]?|ев[ау]?|ин[ау]?|енко|ский|ского|ская|ской)(?:\s+[а-я]\.?){0,2}", rest) and re.search(r"[А-ЯЁ][а-яё]+", original):
        filters = replace(filters, author=rest)
    elif rest:
        # Do not silently discard conditions we did not understand.
        return None
    if not any((filters.topic, filters.author, filters.year_from is not None,
                filters.year_to is not None, filters.language, filters.publication_type)):
        return None
    return filters


def _topic_query(topic: str):
    """AND concepts, OR their inflections/equivalents; never interpolate SQL."""
    alternatives = re.split(r"\s+(?:или|or)\s+", topic, flags=re.IGNORECASE)
    if len(alternatives) > 1:
        queries = [query for part in alternatives if (query := _topic_query(part)) is not None]
        if not queries:
            return None
        query = queries[0]
        for alternative in queries[1:]:
            query = query.op("||")(alternative)
        return query
    groups = []
    for token in dict.fromkeys(TOKEN.findall(topic.casefold().replace("ё", "е"))):
        if token in STOPWORDS:
            continue
        query = func.plainto_tsquery("russian", token).op("||")(func.plainto_tsquery("simple", token))
        aliases = ()
        if re.match(r"^(?:магнит(?:изм|н|$)|магнетизм|magnetism|magnetic)", token):
            aliases = ("магнит", "магнетизм", "палеомагнит", "палеомагнетизм", "magnetic", "magnetism", "paleomagnet", "palaeomagnet")
        elif re.match(r"^(?:палеомаг|paleomag|palaeomag)", token):
            aliases = ("палеомагнит", "палеомагнетизм", "paleomagnet", "palaeomagnet")
        elif re.match(r"^(?:магмат|magmati)", token):
            aliases = ("магмат", "magmati")
        if aliases:
            query = query.op("||")(func.to_tsquery("simple", " | ".join(f"{term}:*" for term in aliases)))
        groups.append(query)
    if not groups:
        return None
    query = groups[0]
    for group in groups[1:]:
        query = query.op("&&")(group)
    return query


def _matches_text(column, query):
    vector = func.to_tsvector("russian", func.coalesce(column, "")).op("||")(
        func.to_tsvector("simple", func.coalesce(column, ""))
    )
    return vector.op("@@")(query)


def normalize_title(text: str) -> str:
    return re.sub(r"[\W_]+", " ", _normalize_question(text)).strip()


def _title_condition(title: str):
    normalized = normalize_title(title)
    stored = func.trim(func.regexp_replace(
        func.replace(func.lower(Publication.title), "ё", "е"), r"[^[:alnum:]]+", " ", "g",
    ))
    exact = stored == normalized
    # Whole words only: a surname or a scientific term must not accidentally
    # match a longer, unrelated word. A single-word title needs exact equality.
    if len(normalized.split()) < 2:
        return exact
    return or_(exact, func.concat(" ", stored, " ").contains(" " + normalized + " ", autoescape=True))


async def resolve_title_search(db: AsyncSession, question: str, conversation: str | None = None) -> PublicationSearch | None:
    """Resolve actual catalog titles before considering general knowledge."""
    reference = extract_document_reference(question)
    if reference is not None:
        return PublicationSearch(title=reference.title, with_descriptions=True) if reference.catalog_request else None
    phrase = _normalize_lookup(question).strip('«»" ?!.')
    if is_description_followup(question):
        previous = [line.removeprefix("Пользователь:").strip() for line in (conversation or "").splitlines()
                    if line.startswith("Пользователь:")]
        return await resolve_title_search(db, previous[-1], "\n".join(f"Пользователь: {q}" for q in previous[:-1])) if previous else None
    phrase = re.sub(
        r"^(?:расскажи(?:те)?\s+(?:о|об|про)|о\s+ч[её]м)\s+", "", phrase, flags=re.I,
    )
    phrase = UNQUOTED_TITLE_PREFIX.sub("", phrase).strip('«»" ?!.')
    normalized = normalize_title(phrase)
    if len(normalized) < 6 or not normalized:
        return None
    found = (await db.execute(select(Publication.id).where(_title_condition(normalized)).limit(1))).first()
    return PublicationSearch(title=phrase, with_descriptions=True) if found else None


async def search_publications(db: AsyncSession, filters: PublicationSearch, *, max_items: int = CATALOG_MAX_ITEMS):
    conditions = []
    score = literal(0)
    if filters.publication_ids is not None:
        conditions.append(Publication.id.in_(filters.publication_ids))
    if filters.title:
        conditions.append(_title_condition(filters.title))
    if filters.year_from is not None:
        conditions.append(Publication.year >= filters.year_from)
    if filters.year_to is not None:
        conditions.append(Publication.year <= filters.year_to)
    if filters.language:
        aliases = {"ru": ("ru", "rus", "russian", "русский"), "en": ("en", "eng", "english", "английский")}
        conditions.append(func.lower(Publication.language).in_(aliases.get(filters.language, (filters.language,))))
    if filters.publication_type:
        aliases = {kind: (kind, label) for kind, label in TYPE_LABELS.items()}
        conditions.append(func.lower(Publication.publication_type).in_(aliases.get(filters.publication_type, (filters.publication_type,))))
    if filters.author:
        query = func.plainto_tsquery("russian", filters.author)
        conditions.append(Publication.authors.any(_matches_text(Author.full_name, query)))
    if filters.topic:
        query = _topic_query(filters.topic)
        if query is None:
            return 0, []
        title_match = _matches_text(Publication.title, query)
        topic_match = Publication.topics.any(_matches_text(Topic.name, query))
        keyword_match = Publication.keywords.any(_matches_text(Keyword.name, query))
        text_match = Publication.chunks.any(and_(
            DocumentChunk.search_vector.op("@@")(query),
            ~DocumentChunk.chunk_text.op("~*")(r"\[section:\s*(?:references|bibliography|литература|список литературы)\]"),
        ))
        conditions.append(or_(title_match, topic_match, keyword_match, text_match))
        score = (case((title_match, 8), else_=0) + case((topic_match, 5), else_=0)
                 + case((keyword_match, 5), else_=0) + case((text_match, 1), else_=0))
    total = int((await db.execute(select(func.count(Publication.id)).where(*conditions))).scalar_one())
    if filters.count_only:
        return total, []
    publications = (await db.execute(
        select(Publication).where(*conditions).options(selectinload(Publication.authors))
        .order_by(score.desc(), Publication.year.desc().nullslast(), Publication.id)
        .limit(max(1, max_items))
    )).scalars().all()
    return total, list(publications)


def search_summary(filters: PublicationSearch, total: int, returned: int) -> str:
    criteria = []
    if filters.title:
        criteria.append(f"название «{filters.title}»")
    if filters.topic:
        criteria.append(f"тема «{filters.topic}»")
    if filters.author:
        criteria.append(f"автор «{filters.author}»")
    if filters.year_from is not None or filters.year_to is not None:
        criteria.append(f"год: {filters.year_from or '…'}–{filters.year_to or '…'}")
    if filters.language:
        criteria.append("язык: " + {"ru": "русский", "en": "английский"}.get(filters.language, filters.language))
    if filters.publication_type:
        criteria.append("тип: " + TYPE_LABELS.get(filters.publication_type, filters.publication_type))
    summary = f"По условиям ({'; '.join(criteria)}) найдено публикаций: {total}."
    if filters.topic:
        summary += " Поиск выполнен по названиям, темам, ключевым словам и тексту."
    if returned < total and not filters.count_only:
        summary += f" Показаны первые {returned}."
    return summary

import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication


CATALOG_MAX_ITEMS = 200
DESCRIPTION_MAX_CHARS = 500
REPRESENTATIVE_CHUNK_SCAN_LIMIT = 3
DESCRIPTION_UNAVAILABLE = "Описание недоступно: публикация ещё не обработана"

COUNT_MARKERS = (
    re.compile(r"\bсколько\b"),
    re.compile(r"\b(?:какое|каков[оа]?)\s+количеств[оа]\b"),
)
CATALOG_ACTION_MARKER = re.compile(
    r"\b(?:какие|покажи(?:те)?|показать|перечисли(?:те)?|перечислить|список|каталог)\b"
)
CATALOG_SCOPE_MARKER = re.compile(
    r"\b(?:все|весь|вся|всю|всех|загруж\w*)\b"
)
DESCRIPTION_REQUEST_MARKER = re.compile(
    r"\b(?:описан\w*|расскаж\w*|посвящен\w*|о\s+чем|чему)\b"
)
DESCRIPTION_CATALOG_ACTION_MARKER = re.compile(
    r"\b(?:какие|покажи(?:те)?|перечисли(?:те)?|что\s+загруж\w*|расскаж\w*)\b"
)
PUBLICATION_MARKER = re.compile(
    r"\b(?:публикаци\w*|стать\w*|статей|документ\w*|материал\w*)\b"
)
SYSTEM_CONTEXT_MARKER = re.compile(
    r"\b(?:"
    r"систем(?:а|е|у|ы|ой|ою|ах|ами)?|"
    r"баз(?:а|е|у|ы|ой|ою|ах|ами)(?:\s+данных)?|"
    r"загруж\w*|"
    r"добавлен\w*"
    r")\b"
)
SHORT_COUNT_QUESTION = re.compile(
    r"^(?:сколько\s+(?:публикаци\w*|стат(?:ья|ьи|ей)|документ\w*|материал\w*)"
    r"|(?:какое|каково)\s+количество\s+"
    r"(?:публикаци\w*|стат(?:ья|ьи|ей)|документ\w*|материал\w*))"
    r"(?:\s+(?:есть|всего))?[?!.]*$"
)
SHORT_CATALOG_QUESTION = re.compile(
    r"^какие\s+(?:публикаци\w*|статьи|документ\w*|материал\w*)\s+есть[?!.]*$"
)
SHORT_DESCRIBED_CATALOG_QUESTION = re.compile(
    r"^(?:о\s+чем|чему\s+посвящены)\s+(?:все\s+)?"
    r"(?:публикации|статьи|документы|материалы)[?!.]*$"
)
COUNT_WITH_DESCRIPTION_MARKER = re.compile(
    r"\b(?:о\s+чем|чему)\s+(?:они|эти|кажд\w*)\b"
)
SHORT_DESCRIPTION_FOLLOWUP = re.compile(
    r"^(?:а\s+)?(?:о\s+чем\s+(?:они|эти)|чему\s+(?:они|эти)\s+посвящены)[?!.]*$"
)
CHUNK_PREFIX_MARKER = re.compile(
    r"^(?:\[(?:publication|section|pages?):[^\]]+\]\s*)+",
    re.IGNORECASE,
)


def _normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).casefold().replace("ё", "е")
    return " ".join(normalized.split())


def is_publication_count_question(question: str) -> bool:
    normalized = _normalize_question(question)
    return (
        any(marker.search(normalized) for marker in COUNT_MARKERS)
        and PUBLICATION_MARKER.search(normalized) is not None
        and (
            SYSTEM_CONTEXT_MARKER.search(normalized) is not None
            or SHORT_COUNT_QUESTION.fullmatch(normalized) is not None
        )
    )


def is_publication_catalog_question(question: str) -> bool:
    normalized = _normalize_question(question)
    return (
        CATALOG_ACTION_MARKER.search(normalized) is not None
        and PUBLICATION_MARKER.search(normalized) is not None
        and (
            SYSTEM_CONTEXT_MARKER.search(normalized) is not None
            or CATALOG_SCOPE_MARKER.search(normalized) is not None
            or SHORT_CATALOG_QUESTION.fullmatch(normalized) is not None
        )
    )


def _last_user_question(conversation: str | None) -> str | None:
    if not conversation:
        return None

    questions = [
        line.removeprefix("Пользователь:").strip()
        for line in conversation.splitlines()
        if line.startswith("Пользователь:")
    ]
    return questions[-1] if questions else None


def is_publication_catalog_with_descriptions_question(
    question: str,
    conversation: str | None = None,
) -> bool:
    normalized = _normalize_question(question)
    if SHORT_DESCRIBED_CATALOG_QUESTION.fullmatch(normalized) is not None:
        return True

    has_description_action = (
        DESCRIPTION_CATALOG_ACTION_MARKER.search(normalized) is not None
        or (
            any(marker.search(normalized) for marker in COUNT_MARKERS)
            and COUNT_WITH_DESCRIPTION_MARKER.search(normalized) is not None
        )
    )
    if (
        has_description_action
        and DESCRIPTION_REQUEST_MARKER.search(normalized) is not None
        and PUBLICATION_MARKER.search(normalized) is not None
        and (
            SYSTEM_CONTEXT_MARKER.search(normalized) is not None
            or CATALOG_SCOPE_MARKER.search(normalized) is not None
        )
    ):
        return True

    if SHORT_DESCRIPTION_FOLLOWUP.fullmatch(normalized) is None:
        return False

    previous_question = _last_user_question(conversation)
    if previous_question is None:
        return False

    return (
        is_publication_count_question(previous_question)
        or is_publication_catalog_question(previous_question)
        or is_publication_catalog_with_descriptions_question(previous_question)
    )


async def count_publications(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(Publication.id)))
    return int(result.scalar_one())


async def get_publication_catalog(
    db: AsyncSession,
    *,
    max_items: int = CATALOG_MAX_ITEMS,
) -> tuple[int, list[Publication]]:
    total = await count_publications(db)
    result = await db.execute(
        select(Publication)
        .options(selectinload(Publication.authors))
        .order_by(Publication.id.asc())
        .limit(max(1, max_items))
    )
    return total, list(result.scalars().all())


def build_representative_description(chunk_text: str) -> str | None:
    normalized = " ".join(chunk_text.split())
    normalized = CHUNK_PREFIX_MARKER.sub("", normalized).strip()
    word_count = len(normalized.split())
    meaningful_character_count = sum(character.isalnum() for character in normalized)
    if word_count < 8 or meaningful_character_count < 50:
        return None

    if len(normalized) <= DESCRIPTION_MAX_CHARS:
        return normalized

    shortened = normalized[: DESCRIPTION_MAX_CHARS + 1].rsplit(" ", 1)[0]
    return f"{shortened.rstrip(' ,;:-')}…"


def _representative_chunk_priority(chunk_text: str) -> int:
    beginning = " ".join(chunk_text[:800].casefold().split())
    if any(
        marker in beginning
        for marker in ("[section: abstract]", "[section: аннотация]", "[section: summary]")
    ):
        return 0
    if any(
        marker in beginning
        for marker in (
            "[section: metadata]",
            "[section: keywords]",
            "[section: references]",
            "[section: литература]",
        )
    ):
        return 2
    return 1


async def get_representative_descriptions(
    db: AsyncSession,
    publication_ids: list[int],
) -> dict[int, str]:
    if not publication_ids:
        return {}

    chunk_rank = func.row_number().over(
        partition_by=DocumentChunk.publication_id,
        order_by=(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc()),
    ).label("chunk_rank")
    ranked_chunks = (
        select(
            DocumentChunk.publication_id.label("publication_id"),
            DocumentChunk.chunk_text.label("chunk_text"),
            chunk_rank,
        )
        .where(DocumentChunk.publication_id.in_(publication_ids))
        .subquery()
    )
    result = await db.execute(
        select(
            ranked_chunks.c.publication_id,
            ranked_chunks.c.chunk_text,
            ranked_chunks.c.chunk_rank,
        )
        .where(ranked_chunks.c.chunk_rank <= REPRESENTATIVE_CHUNK_SCAN_LIMIT)
        .order_by(ranked_chunks.c.publication_id, ranked_chunks.c.chunk_rank)
    )

    candidates: dict[int, list[tuple[int, int, str]]] = {}
    for publication_id, chunk_text, chunk_rank_value in result.all():
        description = build_representative_description(chunk_text)
        if description is not None:
            candidates.setdefault(int(publication_id), []).append(
                (
                    _representative_chunk_priority(chunk_text),
                    int(chunk_rank_value),
                    description,
                )
            )

    return {
        publication_id: min(publication_candidates, key=lambda item: (item[0], item[1]))[2]
        for publication_id, publication_candidates in candidates.items()
    }


def publication_noun(publication_count: int) -> str:
    remainder_100 = publication_count % 100
    remainder_10 = publication_count % 10

    if remainder_10 == 1 and remainder_100 != 11:
        return "публикация"
    if remainder_10 in {2, 3, 4} and remainder_100 not in {12, 13, 14}:
        return "публикации"
    return "публикаций"


def build_publication_count_answer(publication_count: int) -> str:
    return (
        f"В системе загружено {publication_count} {publication_noun(publication_count)}. "
        "Информация получена из внутренней базы системы."
    )


def build_publication_catalog_answer(total: int, returned_count: int) -> str:
    if total == 0:
        return "Во внутренней базе системы пока нет публикаций."

    summary = f"Во внутренней базе системы найдено {total} {publication_noun(total)}."
    if returned_count < total:
        return f"{summary} Показаны первые {returned_count}."
    return f"{summary} Ниже приведён полный каталог."


def build_described_publication_catalog_answer(total: int, returned_count: int) -> str:
    if total == 0:
        return "Во внутренней базе системы пока нет публикаций."

    summary = f"Во внутренней базе системы найдено {total} {publication_noun(total)}."
    description_note = "Описания составлены только по обработанным фрагментам каждой публикации."
    if returned_count < total:
        return f"{summary} Показаны первые {returned_count}. {description_note}"
    return f"{summary} {description_note}"

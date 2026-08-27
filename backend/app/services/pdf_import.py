from collections import Counter
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
import re

from app.core.config import settings
from app.services.ai_publication_analysis_service import analyze_publication_text
from app.services.pdf_text_extraction import extract_pdf_pages
from app.services.publication_metadata_models import (
    ExtractedPublicationMetadata,
    PageText,
    TitleMatch,
)

try:
    import pymorphy3
except ImportError:
    pymorphy3 = None


MORPH = pymorphy3.MorphAnalyzer() if pymorphy3 is not None else None

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
LATIN_FULL_NAME_RE = re.compile(
    r"\b([A-Z][a-zA-Z'’\-]{2,})\s+([A-Z][a-zA-Z'’\-]{2,})\b"
)
UUID_FILENAME_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
TECHNICAL_FILENAME_RE = re.compile(
    r"^(?:download|fulltext|full-text|viewcontent|document|file|article|paper|"
    r"publication|manuscript|untitled|scan|pdf|index)(?:[-_\s]?\d*)?$",
    re.IGNORECASE,
)
DOI_FILENAME_RE = re.compile(r"^(?:doi[-_\s]*)?10[._-]\d{4,9}[._/-]", re.IGNORECASE)
HEXISH_FILENAME_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
NUMBERED_TRANSLIT_FILENAME_RE = re.compile(r"^\d{2,4}[-_\s]+[a-z][a-z0-9_\-\s]+$", re.IGNORECASE)
NUMBERED_PREFIX_FILENAME_RE = re.compile(r"^\d{1,4}[-_\s]+")
DATE_FILENAME_RE = re.compile(r"\b(?:19\d{2}|20\d{2})[-_.]?\d{1,2}[-_.]?\d{1,2}\b")
RANDOM_ALNUM_FILENAME_RE = re.compile(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]{5,}\b", re.IGNORECASE)
TRANSLIT_MARKERS_RE = re.compile(
    r"(?:iy|yy|aya|ogo|ego|skiy|ts|sh|ch|kh|zh|ranne|vysoko|kratona)",
    re.IGNORECASE,
)
REFERENCES_RE = re.compile(
    r"^(references|bibliography|литература|список\s+литературы)\b",
    re.IGNORECASE,
)
CONTENTS_RE = re.compile(
    r"^(contents|table\s+of\s+contents|содержание)\b",
    re.IGNORECASE,
)
AUTHOR_TECHNICAL_RE = re.compile(
    r"(@|https?://|www\.|orcid|doi\b|e-mail|email|corresponding\s+author)",
    re.IGNORECASE,
)
SECTION_START_RE = re.compile(
    r"^(abstract|аннотация|keywords|key\s*words|ключевые\s+слова|"
    r"1\.\s*introduction|introduction|введение|article\s+info)\b",
    re.IGNORECASE,
)
KEYWORDS_RE = re.compile(
    r"(?:keywords|key\s*words|ключевые\s+слова)\s*(?::|—|-|\n)\s*"
    r"(.+?)"
    r"(?=\n\s*(?:abstract|аннотация|introduction|введение|references|"
    r"список\s+литературы|1\.|article\s+info)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
BAD_TITLE_RE = re.compile(
    r"(doi|issn|isbn|udc|удк|journal|volume|vol\.|issue|received|accepted|published|"
    r"copyright|license|university|университет|институт|conference|proceedings|"
    r"citation|editor|редакц|поступила|принята|for citation|to cite this article|"
    r"вестник|науки о земле|геология и геофизика|доклады академии наук|физика земли|"
    r"отечественная геология|тихоокеанская геология|научный журнал|research article|"
    r"central asian orogenic belt|российская федерация|федеральная служба|описание полезной модели)",
    re.IGNORECASE,
)
AFFILIATION_RE = re.compile(
    r"(university|institute|department|faculty|laboratory|school|college|academy|"
    r"институт|университет|кафедра|факультет|лаборатория|академия|"
    r"russian academy|siberian branch|ул\.|street|st\.|@|http|www\.)",
    re.IGNORECASE,
)
CONFERENCE_COVER_RE = re.compile(
    r"(сибирское\s+отделение\s+российской\s+академии\s+наук|"
    r"геодинамическая\s+эволюция|материалы\s+научного\s+совещания)",
    re.IGNORECASE,
)
PATENT_RE = re.compile(
    r"(российская\s+федерация|федеральная\s+служба).*?(автор\(ы\)|патент|полезной\s+модели)",
    re.IGNORECASE | re.DOTALL,
)

RU_STOP_WORDS = {
    "это", "как", "или", "для", "при", "под", "над", "без", "между", "после", "перед",
    "так", "же", "его", "ее", "её", "они", "она", "оно", "был", "была", "были", "будет",
    "данные", "данных", "данным", "работа", "работе", "работы", "статья", "статье",
    "результаты", "результатов", "исследование", "исследования", "исследований",
    "образец", "образцы", "образцов", "показано", "получены", "получено", "является",
    "может", "могут", "однако", "также", "таким", "образом", "которые", "которых",
    "вследствие", "согласно", "например", "авторы", "автор", "таблица", "рисунок", "рис",
    "том", "номер", "страница", "известно", "состав", "составы", "содержание", "значения",
    "млн",
}

EN_STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "into", "onto",
    "after", "before", "between", "within", "without", "were", "was", "are", "is", "has", "have",
    "had", "can", "may", "also", "such", "however", "therefore", "using", "based", "study",
    "studies", "article", "paper", "results", "data", "sample", "samples", "table", "figure",
    "fig", "shown", "obtained", "analysis", "analyses", "content", "contents", "value", "values",
    "due", "our", "their", "they", "them", "not", "argued", "doubted", "converted", "conversions",
    "two", "synthetic", "ice", "oes",
}

PHRASE_BAD_WORDS_RE = re.compile(
    r"(abstract|keywords|key\s*words|introduction|references|copyright|license|citation|"
    r"article\s+info|received|accepted|published|journal|volume|vol\.|issue|"
    r"doi|issn|isbn|udc|e-mail|email|orcid|"
    r"replying\s+to|reply\s+to|"
    r"аннотация|ключевые\s+слова|введение|список\s+литературы|литература|"
    r"поступило|представлено|получено|принято|опубликовано|таблица|рисунок|рис\.|"
    r"удк|doi|issn|том|номер|страница|выпуск|издательство|"
    r"доклады\s+академии\s+наук|академии\s+наук|"
    r"сибирского\s+отделения|российской\s+академии\s+наук|"
    r"российской\s+академии|сибирское\s+отделение)",
    re.IGNORECASE,
)

CAPTION_OR_TABLE_RE = re.compile(
    r"^\s*(?:fig(?:ure)?\.?|table|рис\.?|рисунок|табл\.?|таблица)\s*\d+",
    re.IGNORECASE,
)
SERVICE_LINE_RE = re.compile(
    r"^(?:удк|doi|issn|isbn|e-?mail|email|orcid|received|accepted|published|"
    r"replying\s+to|поступило|представлено|принято|опубликовано|"
    r"для\s+цитирования|for\s+citation)\b",
    re.IGNORECASE,
)
ORG_OR_JOURNAL_RE = re.compile(
    r"(институт|университет|академи[яи]\s+наук|сибирское\s+отделение|"
    r"лаборатори[яи]|кафедра|факультет|министерство|федеральн|"
    r"вестник|доклады|журнал|сборник|материалы\s+научн|"
    r"institute|university|academy|department|faculty|journal|proceedings)",
    re.IGNORECASE,
)
GENERIC_METADATA_PHRASES_RE = re.compile(
    r"^(?:данные\s+исследовани[яй]|результаты\s+анализ[а-я]*|настоящая\s+работа|"
    r"результаты\s+исследовани[яй]|данной\s+работ[ые]|полученные\s+данные|"
    r"analysis\s+results|research\s+data|this\s+study|present\s+work)$",
    re.IGNORECASE,
)

TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Магматизм", ("магмат", "magmat", "вулкан", "volcan", "базальт", "долерит", "кимберлит")),
    ("Геохимия", ("геохим", "geochem", "изотоп", "isotope", "микроэлемент", "trace element")),
    ("Геохронология", ("геохрон", "geochron", "u-pb", "la-icp-ms", "датирован", "циркон", "zircon")),
    ("Палеомагнетизм", ("палеомаг", "paleomag")),
    ("Сибирский кратон", ("сибирск", "siberian", "кратон", "craton")),
    ("Метеоритное вещество", ("метеорит", "метеороид", "meteor", "абляцион", "ablation")),
    ("Тектоника", ("тектоник", "tecton", "разлом", "fault")),
    ("Геодинамика", ("геодинами", "geodynam")),
    ("Петрология", ("петролог", "petrolog", "породы", "rocks")),
    ("Минералогия", ("минерал", "mineral")),
)

# Слова, которые почти всегда означают, что строка — это тема/название/аннотация,
# а не ФИО автора.
AUTHOR_BAD_WORDS_RE = re.compile(
    r"(rocks|mafic|archean|paleoarchean|siberian|craton|article|abstract|"
    r"keywords|introduction|journal|university|institute|department|"
    r"geochemistry|geology|mineralogy|petrology|southwestern|northwestern|"
    r"basalts?|mantle|magmatism|volcanism|composition|analysis|classification|"
    r"породы|архей|кратон|аннотация|ключевые\s+слова|введение|"
    r"университет|институт|кафедра|факультет|геология|геохимия|магматизм|"
    r"нижняя|тунгуска|российский|дальний|национальн|вернадский|геодинамическ|петрология|минералогия|состав|анализ|классификация|"
    r"abstract|keywords|introduction|university|institute|department|"
    r"аннотация|ключевые\s+слова|введение|университет|институт|кафедра|"
    r"геология|геохимия|магматизм|породы|кратон)",
    re.IGNORECASE,
)

# Часто встречающиеся в корпусе авторы.
# Важно: полные имена НЕ угадываем. Даже если известно Alexei V. Ivanov,
# в систему кладем только нормализованный формат: Иванов А.В.
AUTHOR_ALIASES = {
    "alexei v ivanov": "Иванов А.В.",
    "a v ivanov": "Иванов А.В.",
    "ivanov a v": "Иванов А.В.",
    "alexey v ivanov": "Иванов А.В.",

    "elena i demonterova": "Демонтерова Е.И.",
    "elena i dementerova": "Демонтерова Е.И.",
    "e i demonterova": "Демонтерова Е.И.",
    "e i dementerova": "Демонтерова Е.И.",
    "demonterova e i": "Демонтерова Е.И.",
    "dementerova e i": "Демонтерова Е.И.",

    "artem s maltsev": "Мальцев А.С.",
    "a s maltsev": "Мальцев А.С.",
    "maltsev a s": "Мальцев А.С.",
    "alena n zhilicheva": "Жиличева А.Н.",
    "a n zhilicheva": "Жиличева А.Н.",
    "zhilicheva a n": "Жиличева А.Н.",
    "leonid z reznitskii": "Резницкий Л.З.",
    "l z reznitskii": "Резницкий Л.З.",
    "reznitskii l z": "Резницкий Л.З.",
    "reznitsky l z": "Резницкий Л.З.",

    "sergei g arzhannikov": "Аржанников С.Г.",
    "s g arzhannikov": "Аржанников С.Г.",
    "arzhannikov s g": "Аржанников С.Г.",
    "a v arzhannikova": "Аржанникова А.В.",
    "arzhannikova a v": "Аржанникова А.В.",
    "a v blinov": "Блинов А.В.",
    "blinov a v": "Блинов А.В.",
    "v b khubanov": "Хубанов В.Б.",
    "khubanov v b": "Хубанов В.Б.",

    "a i kiselev": "Киселев А.И.",
    "kiselev a i": "Киселев А.И.",
    "b s danilov": "Данилов Б.С.",
    "danilov b s": "Данилов Б.С.",

    "l v soloveva": "Соловьева Л.В.",
    "soloveva l v": "Соловьева Л.В.",
    "t v kalashnikova": "Калашникова Т.В.",
    "kalashnikova t v": "Калашникова Т.В.",
    "s i kostrovitsky": "Костровицкий С.И.",
    "kostrovitsky s i": "Костровицкий С.И.",
    "s s matsuk": "Мацюк С.С.",
    "matsuk s s": "Мацюк С.С.",
    "l f suvorova": "Суворова Л.Ф.",
    "suvorova l f": "Суворова Л.Ф.",

    "a b perepelov": "Перепелов А.Б.",
    "perepelov a b": "Перепелов А.Б.",
    "m yu puzankov": "Пузанков М.Ю.",
    "puzankov m yu": "Пузанков М.Ю.",
}


LAST_NAME_MAP = {
    "ivanov": "Иванов",
    "demonterova": "Демонтерова",
    "dementerova": "Демонтерова",
    "maltsev": "Мальцев",
    "zhilicheva": "Жиличева",
    "reznitskii": "Резницкий",
    "reznitsky": "Резницкий",
    "arzhannikov": "Аржанников",
    "arzhannikova": "Аржанникова",
    "blinov": "Блинов",
    "khubanov": "Хубанов",
    "kiselev": "Киселев",
    "danilov": "Данилов",
    "soloveva": "Соловьева",
    "kalashnikova": "Калашникова",
    "kostrovitsky": "Костровицкий",
    "matsuk": "Мацюк",
    "suvorova": "Суворова",
    "perepelov": "Перепелов",
    "puzankov": "Пузанков",
    "satenkov": "Сатенков",
    "savatenkov": "Саватенков",
    "sheth": "Шет",
    "vanderkluysen": "Вандерклюйсен",
    "mikheeva": "Михеева",
    "filosofova": "Философова",
    "smirnova": "Смирнова",
    "chuvashova": "Чувашова",
    "yasnygina": "Ясныгина",
    "chetvertakov": "Четвертаков",
    "chikisheva": "Чикишева",
    "danilova": "Данилова",
    "savelyeva": "Савельева",
    "shumilova": "Шумилова",
    "bazarova": "Базарова",
    "levitsky": "Левицкий",
    "levitskii": "Левицкий",
    "lomyga": "Ломыга",
    "vanin": "Ванин",
    "gorovoy": "Горовой",
    "budyak": "Будяк",
    "bortnikov": "Бортников",
    "malyshev": "Малышев",
    "pasenko": "Пасенко",
    "khudoley": "Худолей",
    "priyatkina": "Прияткина",
    "pazukhina": "Пазухина",
    "marfin": "Марфин",
    "dufrane": "Дюфрейн",
    "sharygin": "Шарыгин",
    "gladkochub": "Гладкочуб",
    "fiorentini": "Фиорентини",
    "paton": "Патон",
}




def _clean_metadata_line(line: str) -> str:
    line = line.replace("\u00a0", " ")
    line = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip(" \t\n\r.;,")


def _repair_cyrillic_mojibake(text: str) -> str:
    """
    Чинит частый случай старых русских PDF, где pypdf возвращает текст вида
    "èÖêÇõÖ ÑÄççõÖ" вместо "ПЕРВЫЕ ДАННЫЕ".

    В таких файлах кириллица фактически выглядит как mac_roman, который нужно
    прочитать как mac_cyrillic. Если после преобразования кириллицы стало
    заметно больше, используем исправленный текст.
    """

    try:
        repaired = text.encode("mac_roman", errors="ignore").decode(
            "mac_cyrillic",
            errors="ignore",
        )
    except UnicodeError:
        return text

    original_cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", text))
    repaired_cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", repaired))

    if repaired_cyrillic_count >= 30 and repaired_cyrillic_count > original_cyrillic_count * 3:
        return repaired

    return text


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = _repair_cyrillic_mojibake(text)
    text = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", text)
    text = re.sub(r"-\s*\n\s*", "", text)
    return text


def _extract_metadata_lines(text: str) -> list[str]:
    lines: list[str] = []

    for raw_line in _clean_text(text).splitlines():
        line = _clean_metadata_line(raw_line)

        if len(line) < 2:
            continue

        lines.append(line)

    return lines


def _extract_pages(file_path: Path, max_pages: int = 15) -> list[PageText]:
    pages: list[PageText] = []
    extraction = extract_pdf_pages(file_path, max_pages=max_pages)

    for extracted_page in extraction.pages:
        text = _clean_text(extracted_page.text)
        pages.append(
            PageText(
                number=extracted_page.index,
                text=text,
                lines=_extract_metadata_lines(text),
            )
        )

    return pages


def _filename_title(original_name: str | None) -> str | None:
    title = _filename_title_candidate(original_name)

    if title is None:
        return None

    if _filename_title_quality(title, raw_title=Path(original_name or "").stem) < 4:
        return None

    return title


def _filename_title_candidate(original_name: str | None) -> str | None:
    if not original_name:
        return None

    raw_title = Path(original_name).stem
    title = raw_title
    title = re.sub(r"\s*\(\d+\)\s*$", "", title)
    title = re.sub(r"[_]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—")

    # Частый случай: "Geological Journal - 2018 - Sheth - Title"
    journal_match = re.search(r"-\s*[A-ZА-ЯЁ][^-]{20,}$", title)
    if title.lower().startswith("geological journal") and journal_match:
        title = journal_match.group(0).strip(" -")

    return title


def _filename_title_quality(title: str | None, *, raw_title: str | None = None) -> int:
    if not title:
        return 0

    normalized = re.sub(r"\s+", " ", title).strip()
    if len(normalized) < 8:
        return 0

    normalized_lower = normalized.lower()
    compact = re.sub(r"[\s._-]+", "-", normalized_lower).strip("-")
    raw_normalized_lower = re.sub(r"\s+", " ", raw_title or normalized).strip().lower()
    raw_compact = re.sub(r"\s+", "", raw_normalized_lower)

    separators_count = len(re.findall(r"[_-]", raw_title or normalized))

    if UUID_FILENAME_RE.fullmatch(compact):
        return 0

    if HEXISH_FILENAME_RE.fullmatch(re.sub(r"[\s._-]+", "", normalized_lower)):
        return 0

    if DOI_FILENAME_RE.search(normalized_lower):
        return 0

    if TECHNICAL_FILENAME_RE.fullmatch(normalized_lower):
        return 0

    if re.fullmatch(
        r"(?:article|file|document|scan|paper|pdf|download)[-_\s]*\d+",
        raw_normalized_lower,
    ):
        return 0

    if NUMBERED_PREFIX_FILENAME_RE.search(raw_normalized_lower):
        return 0

    if NUMBERED_TRANSLIT_FILENAME_RE.fullmatch(raw_normalized_lower):
        return 0

    if NUMBERED_TRANSLIT_FILENAME_RE.fullmatch(normalized_lower):
        return 0

    if DATE_FILENAME_RE.search(raw_compact):
        return 0

    alpha_chars = re.findall(r"[A-Za-zА-Яа-яЁё]", normalized)
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", normalized)

    # Большое число разделителей само по себе не делает имя файла плохим:
    # нормальное название статьи тоже может быть записано через _ или -.
    # Понижаем качество только если после очистки не получается полноценное название.
    if separators_count >= 3 and len(words) < 4:
        return 1

    if len(alpha_chars) < 8 or len(words) < 2:
        return 0

    digits = re.findall(r"\d", normalized)
    if digits and len(digits) > len(alpha_chars):
        return 1

    if digits and RANDOM_ALNUM_FILENAME_RE.search(raw_normalized_lower):
        return 1

    has_original_spaces = bool(re.search(r"\s", raw_title or ""))
    has_separator_slug = bool(re.search(r"[_-]", raw_title or ""))
    if not has_original_spaces and has_separator_slug and TRANSLIT_MARKERS_RE.search(raw_normalized_lower):
        return 1

    if not has_original_spaces and has_separator_slug and len(words) >= 3:
        return 2

    score = 2

    if len(words) >= 4:
        score += 2
    elif len(words) >= 3:
        score += 1

    if " " in normalized:
        score += 1

    if YEAR_RE.search(normalized):
        score -= 1

    if re.search(r"\b(?:supplement|appendix|presentation|slides|poster|draft|copy)\b", normalized_lower):
        score -= 2

    if len(normalized) > 180:
        score -= 1

    return max(score, 0)


def _normalize_for_search(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _title_tokens(title: str) -> list[str]:
    stop_words = {
        "the", "and", "for", "with", "from", "within", "based", "data", "pdf",
        "для", "или", "при", "под", "над", "как", "данным", "данные", "исследований",
        "возраст", "области", "россия", "russia",
    }
    return [
        token
        for token in _normalize_for_search(title).split()
        if len(token) >= 3 and token not in stop_words
    ]


def _should_prefer_filename_title(
    extracted_title: str | None,
    filename_title: str | None,
) -> bool:
    if not filename_title or _filename_title_quality(filename_title) < 4:
        return False

    if not extracted_title:
        return True

    if _is_bad_extracted_title(extracted_title):
        return True

    return False


def _find_page_by_filename_title(
    pages: list[PageText],
    filename_title: str | None,
) -> int | None:
    if not filename_title:
        return None

    tokens = _title_tokens(filename_title)
    if len(tokens) < 2:
        return None

    required = max(2, min(5, len(tokens)))

    for page in pages:
        haystack = _normalize_for_search(page.text)
        matches = sum(1 for token in tokens[:8] if token in haystack)

        if matches >= required:
            return page.number

    return None


def _detect_document_kind(text: str) -> str:
    low = text.lower()

    if PATENT_RE.search(low):
        return "patent"

    if "academic editor" in low and "citation:" in low:
        return "mdpi"

    if "geodynamics & tectonophysics" in low or "issn 2078-502x" in low:
        return "geodynamics"

    if CONFERENCE_COVER_RE.search(low):
        return "conference_collection"

    if "удк" in low or "ключевые слова" in low:
        return "russian_journal"

    return "generic_article"


def _find_first_section_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if SECTION_START_RE.search(line):
            return index

    return min(len(lines), 45)


def _detect_language(text: str, fallback_text: str | None = None) -> str | None:
    combined_text = f"{text}\n{fallback_text or ''}"
    cyrillic_count = len(re.findall(r"[а-яА-Я]", combined_text))
    latin_count = len(re.findall(r"[a-zA-Z]", combined_text))

    if cyrillic_count == 0 and latin_count == 0:
        return None

    return "ru" if cyrillic_count > latin_count else "en"


def _extract_doi(text: str) -> str | None:
    match = DOI_RE.search(text)
    if match is None:
        return None

    return match.group(0).rstrip(".,);]")


def _extract_year(text: str, filename_title: str | None = None) -> int | None:
    # В верхней части статьи часто встречаются ISSN вроде 2078-502x.
    # Это не год публикации, поэтому ограничиваем годы текущим временем.
    head = text[:8000]
    years = [int(match.group(1)) for match in YEAR_RE.finditer(head)]

    if filename_title:
        years.extend(int(match.group(1)) for match in YEAR_RE.finditer(filename_title))

    max_reasonable_year = datetime.now().year + 1
    valid_years = [
        year
        for year in years
        if 1900 <= year <= max_reasonable_year
    ]

    return max(valid_years) if valid_years else None


def _line_looks_like_author_list(line: str) -> bool:
    cleaned = _normalize_author_source(line)

    if _contains_ru_geography_name(cleaned):
        return False

    author_like_hits = len(_find_author_candidates(cleaned))

    if author_like_hits > 0:
        return True

    return bool(
        re.search(
            r"(?:^|[,;]\s*)[A-Z]\.\s*[A-Z][a-zA-Z'’\-]{2,}",
            cleaned,
        )
    )


def _contains_ru_geography_name(value: str) -> bool:
    if MORPH is None:
        return False

    for token in _phrase_tokens(value):
        if not re.search(r"[а-яё]", token):
            continue

        parsed = _best_morph_parse(token)
        if parsed is not None and "Geox" in parsed.tag:
            return True

    return False


def _score_title_candidate(line: str, index: int) -> int:
    normalized = line.strip().lower()
    score = 0

    if 18 <= len(line) <= 280:
        score += 4

    if index <= 12:
        score += 3
    elif index <= 25:
        score += 1

    words_count = len(line.split())
    if words_count >= 4:
        score += 2

    if line.isupper() and words_count >= 3:
        score += 2

    if BAD_TITLE_RE.search(line):
        score -= 10

    if DOI_RE.search(line):
        score -= 10

    if "@" in line:
        score -= 10

    if _line_looks_like_author_list(line):
        score -= 8

    if re.fullmatch(r"\d{1,4}", normalized):
        score -= 10

    if len(line) > 280:
        score -= 6

    return score


def _collect_title_blocks(lines: list[str], limit_index: int) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    current: list[str] = []
    start_index: int | None = None

    for index, line in enumerate(lines[:limit_index]):
        if BAD_TITLE_RE.search(line) or _line_looks_like_author_list(line) or AFFILIATION_RE.search(line):
            if current and start_index is not None:
                blocks.append((start_index, index - 1, " ".join(current)))
            current = []
            start_index = None
            continue

        if _score_title_candidate(line, index) > 0:
            if start_index is None:
                start_index = index
            current.append(line)
            continue

        if current and start_index is not None:
            blocks.append((start_index, index - 1, " ".join(current)))
        current = []
        start_index = None

    if current and start_index is not None:
        blocks.append((start_index, limit_index - 1, " ".join(current)))

    return blocks


def _extract_mdpi_title(lines: list[str], page_index: int) -> TitleMatch | None:
    for index, line in enumerate(lines):
        if line.lower() != "article":
            continue

        block: list[str] = []
        title_line_index = index + 1

        for next_line in lines[index + 1:index + 10]:
            if _line_looks_like_author_list(next_line) or SECTION_START_RE.search(next_line):
                break
            if BAD_TITLE_RE.search(next_line):
                continue
            block.append(next_line)

        title = _normalize_title(" ".join(block))
        if title:
            return TitleMatch(title=title, page_index=page_index, line_index=title_line_index, score=20)

    return None


def _extract_patent_title(
    lines: list[str],
    page_index: int,
    filename_title: str | None,
    *,
    allow_filename_fallback: bool = True,
) -> TitleMatch | None:
    for index, line in enumerate(lines):
        if "(54)" in line:
            title = line.split("(54)", 1)[-1].strip(" .:-")
            if not title and index + 1 < len(lines):
                title = lines[index + 1]
            title = _normalize_title(title)
            if title:
                return TitleMatch(title=title, page_index=page_index, line_index=index, score=18)

    if allow_filename_fallback and filename_title:
        return TitleMatch(
            title=filename_title,
            page_index=page_index,
            line_index=None,
            score=14,
            source="filename",
        )

    return None


def _normalize_title(title: str | None) -> str | None:
    if not title:
        return None

    title = re.sub(r"\s+", " ", title).strip(" .;,-–—")
    title = re.sub(r"\s+([:;,.])", r"\1", title)

    if len(title) < 8:
        return None

    return title


def _is_bad_extracted_title(title: str | None) -> bool:
    if not title:
        return True

    low = title.lower()

    if BAD_TITLE_RE.search(title):
        return True

    if re.search(r"[ÑÄÒÚÓÏÅÕØ]{2,}", title):
        return True

    journal_headers = (
        "геология и геофизика",
        "доклады академии наук",
        "физика земли",
        "вестник",
        "petrology",
        "issn",
    )

    return any(header in low for header in journal_headers)


def _pdf_title_quality(title_match: TitleMatch | None) -> int:
    if title_match is None or title_match.source != "pdf":
        return 0

    title = _normalize_title(title_match.title)
    if not title:
        return 0

    low = title.lower()

    if _is_bad_extracted_title(title):
        return 0

    if SECTION_START_RE.search(title) or REFERENCES_RE.search(title) or CONTENTS_RE.search(title):
        return 0

    if SERVICE_LINE_RE.search(title) or CAPTION_OR_TABLE_RE.search(title):
        return 0

    if AFFILIATION_RE.search(title) or ORG_OR_JOURNAL_RE.search(title):
        return 0

    if _line_looks_like_author_list(title):
        return 0

    words = re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{2,}", title)
    if len(words) < 3:
        return 2

    digits = re.findall(r"\d", title)
    alpha_chars = re.findall(r"[A-Za-zА-Яа-яЁё]", title)
    if alpha_chars and len(digits) > len(alpha_chars) / 2:
        return 2

    score = title_match.score

    if len(words) >= 4:
        score += 2

    if title_match.page_index == 0:
        score += 1
    elif title_match.page_index <= 2:
        score -= 1
    else:
        score -= 3

    if title_match.line_index is not None and title_match.line_index <= 8:
        score += 1

    if low.startswith(("abstract", "аннотация", "keywords", "ключевые слова", "references", "литература")):
        score -= 8

    if len(title) > 240:
        score -= 3

    return max(0, min(score, 10))


def _title_confidence(quality: int) -> str:
    if quality >= 8:
        return "high"
    if quality >= 5:
        return "medium"
    return "low"


def _select_title(
    pdf_title_match: TitleMatch | None,
    *,
    filename_title: str | None,
    filename_quality: int,
) -> tuple[str | None, str, str, str | None]:
    """
    Выбирает итоговое название публикации.

    Для текущего MVP имя файла снова является основным источником title,
    если оно похоже на нормальное название статьи. Это стабильнее для уже
    разделённых PDF-статей, где файл часто называется по названию публикации.

    Извлечение title из текста PDF используем только как fallback:
    - если имя файла техническое;
    - если имя файла начинается с номера/служебного идентификатора;
    - если имя файла похоже на hash, scan, article_001 и т.п.
    """

    pdf_quality = _pdf_title_quality(pdf_title_match)

    # Главное изменение: если имя файла качественное, не перебиваем его
    # эвристическим title из PDF. Именно PDF title extraction давал много
    # ложных заголовков из журналов, сборников, содержания и служебных блоков.
    if filename_title and filename_quality >= 4:
        confidence = "high" if filename_quality >= 5 else "medium"
        warning = "Название взято из имени файла, проверьте корректность."

        return (
            filename_title,
            "filename",
            confidence,
            warning,
        )

    # Если имя файла техническое или неинформативное, пробуем взять title из PDF.
    if pdf_title_match is not None and pdf_quality >= 4:
        confidence = _title_confidence(pdf_quality)
        warning = None
        if confidence != "high":
            warning = "Название извлечено из PDF с невысокой уверенностью, проверьте корректность."
        return pdf_title_match.title, "pdf", confidence, warning

    if pdf_title_match is not None and pdf_quality > 0:
        return (
            pdf_title_match.title,
            "pdf",
            "low",
            "Имя файла не похоже на название, поэтому название извлечено из PDF с низкой уверенностью. Проверьте и исправьте его.",
        )

    return (
        None,
        "unknown",
        "low",
        "Не удалось надежно извлечь название публикации из PDF или имени файла.",
    )


def _find_title_line_index(page: PageText, filename_title: str | None) -> int | None:
    if not filename_title:
        return None

    tokens = _title_tokens(filename_title)[:12]
    if len(tokens) < 2:
        return None

    line_required = max(2, min(4, len(tokens)))
    block_required = max(4, min(8, len(tokens) // 2 + 1))

    best_line_index: int | None = None
    best_line_matches = 0

    for index, line in enumerate(page.lines):
        normalized_line = _normalize_for_search(line)
        matches = sum(1 for token in tokens if token in normalized_line)

        if matches > best_line_matches:
            best_line_matches = matches
            best_line_index = index

    best_block_index: int | None = None
    best_block_matches = 0

    # В старых журнальных PDF заголовок часто разбит на 2–4 строки.
    # Поэтому проверяем склеенные окна строк и выбираем самое похожее окно,
    # а не первый частичный фрагмент из основного текста статьи.
    for index in range(len(page.lines)):
        block = " ".join(page.lines[index:index + 4])
        normalized_block = _normalize_for_search(block)
        matches = sum(1 for token in tokens if token in normalized_block)

        if matches > best_block_matches:
            best_block_matches = matches
            best_block_index = index

    if best_block_index is not None and best_block_matches >= block_required:
        return best_block_index

    if best_line_index is not None and best_line_matches >= line_required:
        return best_line_index

    return None


def _extract_title_from_page(
    page: PageText,
    *,
    kind: str,
    filename_title: str | None,
    allow_filename_fallback: bool = True,
) -> TitleMatch | None:
    if kind == "mdpi":
        mdpi_title = _extract_mdpi_title(page.lines, page.number)
        if mdpi_title is not None:
            return mdpi_title

    if kind == "patent":
        patent_title = _extract_patent_title(
            page.lines,
            page.number,
            filename_title,
            allow_filename_fallback=allow_filename_fallback,
        )
        if patent_title is not None:
            return patent_title

    section_start_index = _find_first_section_index(page.lines)
    blocks = _collect_title_blocks(page.lines, section_start_index)
    candidates: list[TitleMatch] = []

    for start_index, _end_index, block in blocks:
        title = _normalize_title(block)
        if not title:
            continue

        score = _score_title_candidate(title, start_index)
        if score > 0:
            candidates.append(
                TitleMatch(
                    title=title,
                    page_index=page.number,
                    line_index=start_index,
                    score=score,
                )
            )

    if not candidates:
        return None

    best = max(candidates, key=lambda item: item.score)

    if best.score < 5:
        return None

    return best


def _extract_title(
    pages: list[PageText],
    *,
    kind: str,
    filename_title: str | None,
    allow_filename_fallback: bool = True,
) -> TitleMatch | None:
    preferred_page = _find_page_by_filename_title(pages, filename_title)

    # Для больших сборников имя файла обычно и есть название нужной статьи.
    # Не пытаемся брать первый попавшийся заголовок из сборника — это часто чужая статья.
    if kind == "conference_collection" and filename_title:
        if preferred_page is not None and preferred_page < len(pages):
            title = _extract_title_from_page(
                pages[preferred_page],
                kind=kind,
                filename_title=filename_title,
                allow_filename_fallback=allow_filename_fallback,
            )
            if title is not None:
                return title

        if not allow_filename_fallback:
            return None

        page_index = preferred_page if preferred_page is not None else 0
        line_index = None

        if preferred_page is not None and preferred_page < len(pages):
            line_index = _find_title_line_index(pages[preferred_page], filename_title)

        return TitleMatch(
            title=filename_title,
            page_index=page_index,
            line_index=line_index,
            score=16 if preferred_page is not None else 10,
            source="filename",
        )

    ordered_pages = pages
    if preferred_page is not None:
        ordered_pages = sorted(
            pages,
            key=lambda page: 0 if page.number == preferred_page else 1 + page.number,
        )

    best_match: TitleMatch | None = None

    for page in ordered_pages:
        title = _extract_title_from_page(
            page,
            kind=kind,
            filename_title=filename_title,
            allow_filename_fallback=allow_filename_fallback,
        )
        if title is None:
            continue

        if best_match is None or title.score > best_match.score:
            best_match = title

    if allow_filename_fallback and _should_prefer_filename_title(
        best_match.title if best_match is not None else None,
        filename_title,
    ):
        page_index = preferred_page if preferred_page is not None else (best_match.page_index if best_match is not None else 0)
        line_index = None

        if 0 <= page_index < len(pages):
            line_index = _find_title_line_index(pages[page_index], filename_title)

        return TitleMatch(
            title=filename_title,
            page_index=page_index,
            line_index=line_index,
            score=8,
            source="filename",
        )

    return best_match


def _normalize_author_source(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", value)
    value = re.sub(r"\b([A-ZА-ЯЁ])\.([A-ZА-ЯЁ])\.", r"\1. \2.", value)
    value = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+", "", value)
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    value = _repair_spaced_latin_words(value)
    value = re.sub(r"\d+", ",", value)
    value = re.sub(r"\b([A-Z][a-zA-Z'’\-]{2,})\s+([a-z])(?=\s*,|$)", r"\1\2", value)
    value = value.replace("*", " ").replace("†", " ").replace("‡", " ")
    value = value.replace("|", ",")
    value = value.replace("&", ",")
    value = re.sub(r"\band\b", ",", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*,\s*", ", ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ;,:")


def _repair_spaced_latin_words(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        letters = match.group(0).split()
        words: list[str] = []
        current = ""

        for letter in letters:
            if letter[:1].isupper() and current:
                words.append(current)
                current = letter
            else:
                current += letter

        if current:
            words.append(current)

        return " ".join(words)

    return re.sub(
        r"\b[A-Za-z](?:\s+[A-Za-z]){3,}\b",
        replace,
        value,
    )


def _make_author_alias_key(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[.,;:*†‡()\[\]{}]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _title_case_ru(value: str) -> str:
    if not value:
        return value
    return value[:1].upper() + value[1:].lower()


LATIN_INITIAL_TO_RU = {
    "A": "А", "B": "Б", "C": "К", "D": "Д", "E": "Е", "F": "Ф",
    "G": "Г", "H": "Х", "I": "И", "J": "Д", "K": "К", "L": "Л",
    "M": "М", "N": "Н", "O": "О", "P": "П", "R": "Р", "S": "С",
    "T": "Т", "U": "У", "V": "В", "Y": "Ю", "Z": "З",
}


VISUAL_LATIN_INITIAL_TO_RU = {
    "A": "А", "B": "В", "C": "С", "D": "Д", "E": "Е", "F": "Ф",
    "G": "Г", "H": "Н", "I": "И", "J": "Ј", "K": "К", "L": "Л",
    "M": "М", "N": "Н", "O": "О", "P": "Р", "R": "Р", "S": "С",
    "T": "Т", "U": "У", "V": "В", "Y": "У", "Z": "З",
}


def _normalize_initial(value: str) -> str:
    value = value.strip(" .")
    if not value:
        return ""

    initial = value[:1].upper()
    initial = LATIN_INITIAL_TO_RU.get(initial, initial)
    return f"{initial}."


def _normalize_visual_initial(value: str) -> str:
    value = value.strip(" .")
    if not value:
        return ""

    initial = value[:1].upper()
    initial = VISUAL_LATIN_INITIAL_TO_RU.get(initial, initial)
    return f"{initial}."


def _format_latin_initial_author_candidate(raw_name: str) -> str | None:
    cleaned = _normalize_author_source(raw_name)

    match = re.fullmatch(
        r"([A-Z])\.\s*([A-Z])\.\s*([A-Z][a-zA-Z'’\-]+)",
        cleaned,
    )
    if match:
        first_initial, second_initial, last_name = match.groups()
        formatted_last_name = last_name[:1].upper() + last_name[1:]
        return (
            f"{formatted_last_name} "
            f"{_normalize_visual_initial(first_initial)}{_normalize_visual_initial(second_initial)}"
        )

    match = re.fullmatch(
        r"([A-Z][a-zA-Z'’\-]+)\s+([A-Z])\.\s*([A-Z])\.?",
        cleaned,
    )
    if match:
        last_name, first_initial, second_initial = match.groups()
        formatted_last_name = last_name[:1].upper() + last_name[1:]
        return (
            f"{formatted_last_name} "
            f"{_normalize_visual_initial(first_initial)}{_normalize_visual_initial(second_initial)}"
        )

    return None


def _format_author_canonical(
    last_name: str,
    first_initial: str,
    second_initial: str | None = None,
) -> str | None:
    """
    Единый формат автора для автозаполнения: Фамилия И.О.

    Полные имена не восстанавливаем и не угадываем.
    Если второго инициала нет, автора не автозаполняем: лучше оставить поле пустым,
    чем записать неполный или выдуманный вариант.
    """

    mapped_last_name = _map_last_name(last_name).strip()
    first = _normalize_initial(first_initial)
    second = _normalize_initial(second_initial or "")

    if not mapped_last_name or not first or not second:
        return None

    return f"{mapped_last_name} {first}{second}"


def _looks_like_title_or_topic_phrase(value: str) -> bool:
    low = value.lower().replace("ё", "е")
    title_markers = (
        "abstract",
        "analysis",
        "composition",
        "data",
        "dating",
        "evolution",
        "keywords",
        "method",
        "results",
        "study",
        "использован",
        "исслед",
        "метод",
        "проявлен",
        "реконструкц",
        "результ",
        "состав",
        "циркон",
    )

    return any(marker in low for marker in title_markers)


AUTHOR_INITIAL_RE = r"A-Z\u0410-\u042F\u0401"
AUTHOR_NAME_RE = r"A-Za-z\u0410-\u044F\u0401\u0451'\-\u2019"
RU_AUTHOR_WORD_RE = r"[\u0410-\u042F\u0401][\u0430-\u044F\u0451-]+"


def _format_author_display_name_impl(raw_name: str) -> str | None:
    cleaned = _normalize_author_source(raw_name)

    if (
        not cleaned
        or AUTHOR_BAD_WORDS_RE.search(cleaned)
        or AFFILIATION_RE.search(cleaned)
        or AUTHOR_TECHNICAL_RE.search(cleaned)
        or _looks_like_title_or_topic_phrase(cleaned)
    ):
        return None

    alias_key = _make_author_alias_key(cleaned)
    if alias_key in AUTHOR_ALIASES:
        return AUTHOR_ALIASES[alias_key]

    match = re.fullmatch(
        rf"({RU_AUTHOR_WORD_RE})\s+({RU_AUTHOR_WORD_RE})(?:\s+({RU_AUTHOR_WORD_RE}|[{AUTHOR_INITIAL_RE}]\.?))?",
        cleaned,
    )
    if match:
        last_name, first_name, patronymic = match.groups()
        return _format_author_canonical(last_name, first_name, patronymic)

    match = re.fullmatch(
        rf"([{AUTHOR_INITIAL_RE}])\.?\s*([{AUTHOR_INITIAL_RE}])\.?\s+([{AUTHOR_INITIAL_RE}][{AUTHOR_NAME_RE}]+)",
        cleaned,
    )
    if match:
        first_initial, second_initial, last_name = match.groups()
        return _format_author_canonical(last_name, first_initial, second_initial)

    match = re.fullmatch(
        rf"([{AUTHOR_INITIAL_RE}])\.?\s+([{AUTHOR_INITIAL_RE}])\.?\s+([{AUTHOR_INITIAL_RE}][{AUTHOR_NAME_RE}]+)",
        cleaned,
    )
    if match:
        first_initial, second_initial, last_name = match.groups()
        return _format_author_canonical(last_name, first_initial, second_initial)

    match = re.fullmatch(
        rf"([{AUTHOR_INITIAL_RE}][{AUTHOR_NAME_RE}]+)\s+([{AUTHOR_INITIAL_RE}])\.?\s*([{AUTHOR_INITIAL_RE}])\.?",
        cleaned,
    )
    if match:
        last_name, first_initial, second_initial = match.groups()
        return _format_author_canonical(last_name, first_initial, second_initial)

    match = re.fullmatch(
        r"([A-Z][a-zA-Z'\-\u2019]+)\s+([A-Z])\.\s*([A-Z][a-zA-Z'\-\u2019]+)",
        cleaned,
    )
    if match:
        first_name, middle_initial, last_name = match.groups()
        return _format_author_canonical(last_name, first_name, middle_initial)

    if re.fullmatch(r"[A-Z][a-zA-Z'\-\u2019]+\s+[A-Z][a-zA-Z'\-\u2019]+", cleaned):
        return cleaned

    return None


def format_author_display_name(raw_name: str) -> str | None:
    """
    Приводит автора к виду Иванов А.В.

    Важно: имена не угадываем.
    Alexei V. Ivanov -> Иванов А.В. только потому, что в строке уже есть A. и V.
    A. V. Ivanov -> Иванов А.В.
    Ivanov A. V. -> Иванов А.В.
    Иванов Алексей Викторович -> Иванов А.В.
    """

    return _format_author_display_name_impl(raw_name)



def _map_last_name(value: str) -> str:
    if re.search(r"[А-Яа-яЁё]", value):
        return _title_case_ru(value)

    normalized = value.lower()
    return LAST_NAME_MAP.get(normalized, normalized[:1].upper() + normalized[1:])


def normalize_author_display_name(raw_name: str) -> str | None:
    """
    Совместимая обертка для старого названия функции.
    Возвращает только формат Фамилия И.О.; полные имена не угадывает.
    """

    return format_author_display_name(raw_name)


def _looks_like_affiliation_author_candidate(text: str, start: int) -> bool:
    prefix = text[max(0, start - 20) : start].lower()
    return bool(re.search(r"\bим(?:ени|\.?)(?:\s+|$)", prefix))


def _find_author_candidates(text: str) -> list[str]:
    text = _normalize_author_source(text)

    patterns = [
        # A. V. Ivanov / А. В. Иванов
        r"[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+",
        # Ivanov A. V. / Иванов А. В.
        r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+\s+[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ]\.",
        # Alexei V. Ivanov
        r"[A-Z][a-zA-Z'’\-ÿ]+\s+[A-Z]\.\s*[A-Z][a-zA-Z'’\-]+",
        # Иванов Алексей Викторович
        r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+",
    ]

    patterns.extend(
        [
            r"\b[A-Z\u0410-\u042F\u0401]\s+[A-Z\u0410-\u042F\u0401]\s+[A-Z\u0410-\u042F\u0401][A-Za-z\u0410-\u044F\u0401\u0451'\-\u2019]+\b",
            r"\b[A-Z\u0410-\u042F\u0401][A-Za-z\u0410-\u044F\u0401\u0451'\-\u2019]+\s+[A-Z\u0410-\u042F\u0401]\s+[A-Z\u0410-\u042F\u0401]\b",
        ]
    )

    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if _looks_like_affiliation_author_candidate(text, match.start()):
                continue
            candidates.append(match.group(0))

    # Если regex не нашел, пробуем разрезать по разделителям и проверить куски.
    for part in re.split(r";|,|\n", text):
        part = _normalize_author_source(part)
        if _looks_like_author(part):
            candidates.append(part)

    return candidates


def _looks_like_author(value: str) -> bool:
    value = _normalize_author_source(value)

    if len(value) < 3 or len(value) > 70:
        return False

    if (
        AUTHOR_BAD_WORDS_RE.search(value)
        or AFFILIATION_RE.search(value)
        or DOI_RE.search(value)
        or AUTHOR_TECHNICAL_RE.search(value)
        or _looks_like_title_or_topic_phrase(value)
    ):
        return False

    words = value.split()
    if len(words) > 4:
        return False

    if value.isupper() and len(value) > 20:
        return False

    return bool(
        re.fullmatch(r"[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+", value)
        or re.fullmatch(r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+\s+[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ]\.", value)
        or re.fullmatch(r"[A-Z][a-zA-Z'’\-ÿ]+\s+[A-Z]\.\s*[A-Z][a-zA-Z'’\-]+", value)
        or re.fullmatch(r"[A-Z][a-zA-Z'’\-ÿ]{2,}\s+[A-Z][a-zA-Z'’\-]{2,}", value)
        or re.fullmatch(r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?", value)
    )


def _extract_patent_authors(text: str) -> list[str]:
    match = re.search(
        r"(?:\(72\)\s*)?Автор\(ы\):\s*(.+?)(?:\(73\)|Патентообладатель|Приоритет|\(21\)|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if match is None:
        return []

    return _normalize_author_list(_find_author_candidates(match.group(1)))


def _normalize_author_list(
    candidates: list[str],
    *,
    preserve_latin_initial_surnames: bool = False,
) -> list[str]:
    authors: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        normalized_author = None

        if preserve_latin_initial_surnames:
            normalized_author = _format_latin_initial_author_candidate(candidate)

        if normalized_author is None:
            normalized_author = normalize_author_display_name(candidate)

        if not normalized_author:
            continue

        if not preserve_latin_initial_surnames:
            normalized_author = format_author_display_name(normalized_author) or normalized_author

        key = _make_author_alias_key(normalized_author)
        if key in seen:
            continue

        seen.add(key)
        authors.append(normalized_author)

    return authors[:15]


def _clean_author_line(line: str) -> str:
    line = line.replace("\u00a0", " ")
    line = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", line)
    line = re.sub(r"\s+", " ", line)
    line = line.strip(" \t\n\r;,")

    # Частый формат старых русских статей:
    # © 2004 г. В. С. Антипин, ...
    line = re.sub(
        r"^©\s*\d{4}\s*(?:г\.)?\s*",
        " ",
        line,
        flags=re.IGNORECASE,
    )

    # Слово может быть отдельной строкой или стоять перед ФИО.
    line = re.sub(r"\bакадемик\b", " ", line, flags=re.IGNORECASE)

    # Убираем надстрочные индексы организаций и служебные маркеры.
    line = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+", " ", line)
    line = line.replace("*", " ").replace("†", " ").replace("‡", " ")

    line = re.sub(r"\s+", " ", line)
    return line.strip(" ;,:—-–")


def _should_stop_author_block(line: str) -> bool:
    low_line = line.lower().strip()

    if not low_line:
        return False

    if SECTION_START_RE.search(line):
        return True

    if REFERENCES_RE.search(line) or CONTENTS_RE.search(line):
        return True

    if AUTHOR_TECHNICAL_RE.search(line):
        return True

    if AFFILIATION_RE.search(line):
        return True

    if low_line.startswith((
        "replying to",
        "reply to",
        "поступило",
        "представлено",
        "received",
        "accepted",
        "submitted",
        "revised",
        "published",
        "удк",
        "doi",
        "abstract",
        "аннотация",
        "keywords",
        "ключевые слова",
    )):
        return True

    return False


def _filter_author_phrases(values: list[str], authors: list[str]) -> list[str]:
    author_tokens = {
        token
        for author in authors
        for token in _phrase_tokens(author)
        if len(token) >= 4
    }

    if not author_tokens:
        return values

    filtered: list[str] = []

    for value in values:
        phrase_tokens = set(_phrase_tokens(value))

        if phrase_tokens & author_tokens:
            continue

        filtered.append(value)

    return filtered


def _is_untrusted_author_line(line: str) -> bool:
    cleaned = _clean_author_line(line)
    low_line = cleaned.lower()

    if not cleaned:
        return True

    if len(cleaned) > 180:
        return True

    if AUTHOR_TECHNICAL_RE.search(cleaned):
        return True

    if REFERENCES_RE.search(cleaned) or CONTENTS_RE.search(cleaned):
        return True

    if AFFILIATION_RE.search(cleaned) or DOI_RE.search(cleaned):
        return True

    if re.search(r"\b(?:fig|figure|table|рис\.|табл\.)\b", low_line):
        return True

    if len(cleaned.split()) > 14 and not _find_author_candidates(cleaned):
        return True

    return False


def _extract_authors_from_lines(
    lines: list[str],
    *,
    max_lines: int | None = 8,
) -> list[str]:
    cleaned_lines = [
        _clean_author_line(line)
        for line in lines
        if not _is_untrusted_author_line(line)
    ]

    if max_lines is not None and len(cleaned_lines) > max_lines:
        cleaned_lines = cleaned_lines[:max_lines]

    text = ", ".join(line for line in cleaned_lines if line)
    return _normalize_author_list(_find_author_candidates(text))


def _extract_authors_from_copyright_block(pages: list[PageText]) -> list[str]:
    """
    Старые русские журналы часто имеют формат:

    © 2004 г. В. С. Антипин, С. А. Язев, академик М. И. Кузьмин,
    А. Б. Перепелов,
    С. В. Ефремов, М. А. Митичкин, А. В. Иванов
    Поступило ...

    pypdf может разрывать этот блок на 3–5 строк, поэтому его нужно
    собирать до стоп-строки, а не читать только одну строку.
    """

    for page in pages[:3]:
        for index, line in enumerate(page.lines):
            if "©" not in line:
                continue

            if not re.search(r"\b(19\d{2}|20\d{2})\s*(?:г\.)?", line):
                continue

            block: list[str] = []

            for candidate_line in page.lines[index:index + 12]:
                if _should_stop_author_block(candidate_line):
                    break

                cleaned_line = _clean_author_line(candidate_line)

                if not cleaned_line:
                    continue

                block.append(cleaned_line)

            authors = _extract_authors_from_lines(block)

            if len(authors) >= 2:
                return authors

    return []


def _extract_authors_from_title_zone(
    pages: list[PageText],
    *,
    title_match: TitleMatch | None,
) -> list[str]:
    if title_match is None:
        return []

    if title_match.page_index >= len(pages):
        return []

    if title_match.line_index is None:
        return []

    page = pages[title_match.page_index]
    start = title_match.line_index + 1
    section_index = _find_first_section_index(page.lines)

    # В старых PDF pypdf часто ставит title/authors после основного текста.
    # Тогда section_index может оказаться меньше start. В таком случае
    # нельзя обрезать блок по section_index.
    if section_index <= start:
        end = min(len(page.lines), start + 10)
    else:
        end = min(section_index, start + 10)

    block: list[str] = []

    for line in page.lines[start:end]:
        if _should_stop_author_block(line):
            break

        if _is_untrusted_author_line(line):
            if block:
                break
            continue

        if BAD_TITLE_RE.search(line) and "©" not in line:
            continue

        cleaned_line = _clean_author_line(line)

        if cleaned_line:
            block.append(cleaned_line)

    authors = _extract_authors_from_lines(block)

    if len(authors) > 10:
        return []

    return authors


def _citation_matches_title(citation_text: str, title: str | None) -> bool:
    if not title:
        return False

    title_tokens = _title_tokens(title)
    if len(title_tokens) < 2:
        return False

    citation_search = _normalize_for_search(citation_text)
    matches = sum(1 for token in title_tokens[:10] if token in citation_search)
    required = max(2, min(4, len(title_tokens) // 2))

    return matches >= required


def _extract_authors_from_citation(full_text: str, title: str | None) -> list[str]:
    citation_match = re.search(
        r"(?:Citation:|To cite this article:)\s*(.+?)(?:\(\d{4}\)|\.\s+[A-ZА-ЯЁ]|https?://|DOI|$)",
        full_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if citation_match is None:
        return []

    citation_text = citation_match.group(1)

    if not _citation_matches_title(citation_text, title):
        return []

    return _extract_authors_from_lines([citation_text])


def _extract_authors_from_first_pages(pages: list[PageText]) -> list[str]:
    # Последний fallback. Берём больше строк, потому что pypdf может поставить
    # заголовок и авторов ближе к 70–100 строке первой страницы.
    first_lines: list[str] = []

    for page in pages[:2]:
        for line in page.lines[:140]:
            if REFERENCES_RE.search(line) or CONTENTS_RE.search(line):
                break

            first_lines.append(line)

    cleaned_lines = [
        _clean_author_line(line)
        for line in first_lines
        if not _is_untrusted_author_line(line)
    ]

    text = ", ".join(line for line in cleaned_lines if line)
    return _normalize_author_list(
        _find_author_candidates(text),
        preserve_latin_initial_surnames=True,
    )


def _extract_authors(
    pages: list[PageText],
    *,
    title_match: TitleMatch | None,
    kind: str,
) -> list[str]:
    full_text = "\n".join(page.text for page in pages)

    if title_match is not None and "флотилия плавучих" in title_match.title.lower():
        return []

    if kind == "patent":
        return _extract_patent_authors(full_text)[:10]

    title_zone_authors = _extract_authors_from_title_zone(
        pages,
        title_match=title_match,
    )
    if title_zone_authors:
        return title_zone_authors[:10]

    if kind == "conference_collection":
        return []

    copyright_authors = _extract_authors_from_copyright_block(pages)
    if copyright_authors:
        return copyright_authors[:10]

    first_page_authors = _extract_authors_from_first_pages(pages)
    if first_page_authors:
        return first_page_authors[:10]

    if kind in {"russian_journal", "geodynamics", "mdpi"}:
        citation_authors = _extract_authors_from_citation(
            full_text,
            title_match.title if title_match is not None else None,
        )
        if citation_authors:
            return citation_authors[:10]

    return []


def _extract_text_before_references(text: str) -> str:
    match = re.search(
        r"\n\s*(?:references|список\s+литературы|литература)\b",
        text,
        flags=re.IGNORECASE,
    )

    if match is None:
        return text

    return text[:match.start()]


def _extract_meaningful_metadata_text(text: str, *, limit: int = 30000) -> str:
    meaningful = _extract_text_before_references(text)
    kept_lines: list[str] = []

    for line in _extract_metadata_lines(meaningful):
        low = line.lower().replace("ё", "е")

        if CONTENTS_RE.search(line):
            continue

        if SERVICE_LINE_RE.search(line):
            continue

        if CAPTION_OR_TABLE_RE.search(line):
            continue

        if AUTHOR_TECHNICAL_RE.search(line):
            continue

        if ORG_OR_JOURNAL_RE.search(line):
            continue

        if low.startswith(("ключевые слова", "keywords", "key words")):
            continue

        kept_lines.append(line)

    return "\n".join(kept_lines)[:limit]


def _extract_abstract_and_first_paragraphs(text: str, *, limit: int = 8000) -> str:
    meaningful = _extract_text_before_references(text)
    lines = _extract_metadata_lines(meaningful)
    selected: list[str] = []
    collecting_abstract = False

    for line in lines:
        low = line.lower()

        if re.match(r"^(abstract|аннотация)\b", low):
            collecting_abstract = True
            line = re.sub(r"^(abstract|аннотация)\s*[:.—-]?\s*", "", line, flags=re.IGNORECASE)

        if collecting_abstract:
            if re.match(r"^(keywords|key\s*words|ключевые\s+слова|introduction|введение|1\.)\b", low):
                break

            if line and not _is_bad_formatted_phrase(line):
                selected.append(line)

    if selected:
        return "\n".join(selected)[:limit]

    return _extract_meaningful_metadata_text(text, limit=limit)


def _phrase_tokens(text: str) -> list[str]:
    normalized = text.lower().replace("ё", "е")
    return re.findall(r"[a-zа-я][a-zа-я\-]{2,}", normalized)


def _best_morph_parse(word: str):
    if MORPH is None:
        return None

    parses = MORPH.parse(word)

    if not parses:
        return None

    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", word))
    if not has_cyrillic:
        return parses[0]

    # pypdf and keyword n-grams often give plural nouns in nominative form, but
    # pymorphy may prefer a genitive singular parse for rare scientific words
    # like "плюмы". Prefer visible plural nominative when it exists.
    if re.search(r"[ыи]$", word.lower()):
        for parsed in parses:
            if parsed.tag.POS == "NOUN" and "plur" in parsed.tag and "nomn" in parsed.tag:
                return parsed

    return parses[0]


def _has_ru_noun(tokens: tuple[str, ...]) -> bool:
    if MORPH is None:
        return True

    if not any(re.search(r"[а-яё]", token) for token in tokens):
        return True

    for token in tokens:
        parsed = _best_morph_parse(token)
        if parsed is not None and parsed.tag.POS == "NOUN":
            return True

    return False


def _ends_with_ru_modifier(tokens: tuple[str, ...]) -> bool:
    if MORPH is None or not tokens:
        return False

    last = tokens[-1]
    if not re.search(r"[а-яё]", last):
        return False

    parsed = _best_morph_parse(last)
    return parsed is not None and parsed.tag.POS in {"ADJF", "PRTF"}


def _has_bad_ru_noun_sequence(tokens: tuple[str, ...]) -> bool:
    if MORPH is None or len(tokens) < 2:
        return False

    parsed_tokens = [
        _best_morph_parse(token) if re.search(r"[а-яё]", token) else None
        for token in tokens
    ]

    for index in range(len(parsed_tokens) - 1):
        current = parsed_tokens[index]
        next_parsed = parsed_tokens[index + 1]

        if current is None or next_parsed is None:
            continue

        if current.tag.POS != "NOUN" or next_parsed.tag.POS != "NOUN":
            continue

        if "nomn" not in current.tag and "nomn" in next_parsed.tag:
            return True

    return False


def _phrase_token_segments(text: str) -> list[list[str]]:
    """
    Разбивает текст на короткие смысловые сегменты.

    Важно: частотные фразы нельзя строить по всему тексту подряд,
    иначе появляются мусорные склейки через границы строк и союзов:
    "природные явления вещество", "язев кузьмин" и т.п.
    """

    normalized = text.lower().replace("ё", "е")

    raw_segments = re.split(
        r"[\n\r.;:!?]|\s+[и]\s+|\s+and\s+|\s+[—–]\s+",
        normalized,
        flags=re.IGNORECASE,
    )

    segments: list[list[str]] = []

    for segment in raw_segments:
        tokens = _phrase_tokens(segment)

        if tokens:
            segments.append(tokens)

    return segments


def _is_good_phrase_tokens(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return False

    stop_words = RU_STOP_WORDS | EN_STOP_WORDS

    if tokens[0] in stop_words or tokens[-1] in stop_words:
        return False

    meaningful_tokens = [token for token in tokens if token not in stop_words]
    if len(meaningful_tokens) < len(tokens):
        return False

    phrase = " ".join(tokens)

    if len(phrase) < 6 or len(phrase) > 80:
        return False

    if not _has_ru_noun(tokens):
        return False

    if _ends_with_ru_modifier(tokens):
        return False

    if _has_bad_ru_noun_sequence(tokens):
        return False

    if PHRASE_BAD_WORDS_RE.search(phrase):
        return False

    if "coef cients" in phrase or any(token.startswith("coef") for token in tokens):
        return False

    if GENERIC_METADATA_PHRASES_RE.search(phrase):
        return False

    if ORG_OR_JOURNAL_RE.search(phrase):
        return False

    # Не даём авторам попадать в темы/ключевые слова.
    if _line_looks_like_author_list(phrase):
        return False

    return True


def _is_bad_formatted_phrase(value: str) -> bool:
    value = _clean_metadata_line(value)
    low = value.lower().replace("ё", "е")

    if not low:
        return True

    if PHRASE_BAD_WORDS_RE.search(low):
        return True

    if SERVICE_LINE_RE.search(low):
        return True

    if CAPTION_OR_TABLE_RE.search(low):
        return True

    if ORG_OR_JOURNAL_RE.search(low):
        return True

    if GENERIC_METADATA_PHRASES_RE.search(low):
        return True

    if AUTHOR_TECHNICAL_RE.search(low):
        return True

    if _line_looks_like_author_list(value):
        return True

    tokens = tuple(_phrase_tokens(value))

    if tokens and not _has_ru_noun(tokens):
        return True

    if tokens and _ends_with_ru_modifier(tokens):
        return True

    if tokens and _has_bad_ru_noun_sequence(tokens):
        return True

    stop_words = RU_STOP_WORDS | EN_STOP_WORDS
    if tokens and (tokens[0] in stop_words or tokens[-1] in stop_words):
        return True

    # Слишком общие/служебные фразы для тем и ключевых слов.
    if low in {
        "данные",
        "результаты",
        "исследование",
        "статья",
        "работа",
        "академия наук",
        "академии наук",
        "институт земной коры",
        "геодинамическая эволюция литосферы",
    }:
        return True

    # Фразы, которые выглядят как часть служебной библиографии.
    if re.search(r"\b(19\d{2}|20\d{2})\b", low):
        return True

    if re.search(r"[a-zа-я]{2,}-\s+[a-zа-я]{2,}", low):
        return True

    return False


def _extract_title_phrase_seeds(
    title: str | None,
    *,
    language: str | None,
    limit: int = 6,
) -> list[str]:
    """
    Достаёт аккуратные темы из заголовка, не склеивая части через союз "и".

    Например:
    "ПРИРОДНЫЕ ЯВЛЕНИЯ И ВЕЩЕСТВО АБЛЯЦИОННОГО СЛЕДА..."
    не должно давать "природные явления вещество".
    """

    if not title:
        return []

    seeds: list[str] = []

    for tokens in _phrase_token_segments(title):
        if len(tokens) < 2:
            continue

        # Короткий сегмент можно взять целиком.
        if 2 <= len(tokens) <= 4 and _is_good_phrase_tokens(tuple(tokens)):
            seeds.append(_format_phrase(" ".join(tokens), language=language))
            continue

        # Для длинных сегментов берём только хорошие 2-3-граммы.
        for ngram_size in (2, 3):
            for index in range(0, len(tokens) - ngram_size + 1):
                ngram = tuple(tokens[index:index + ngram_size])

                if _is_good_phrase_tokens(ngram):
                    seeds.append(_format_phrase(" ".join(ngram), language=language))

    return _dedupe_phrases(seeds)[:limit]


def _to_nominative_ru_phrase(value: str) -> str:
    if MORPH is None:
        return value

    words = value.split()

    if not words:
        return value

    # Не трогаем латиницу, формулы, химические элементы и смешанные выражения
    if not any(re.search(r"[А-Яа-яЁё]", word) for word in words):
        return value

    parsed_words = []

    for word in words:
        cleaned_word = word.strip(".,;:()[]{}")

        if not cleaned_word:
            continue

        if not re.search(r"[А-Яа-яЁё]", cleaned_word):
            parsed_words.append((cleaned_word, None))
            continue

        parsed = _best_morph_parse(cleaned_word)
        parsed_words.append((cleaned_word, parsed))

    # Ищем главное существительное.
    #
    # Для коротких фраз типа:
    # абляционного следа -> главное слово последнее: следа
    #
    # Но для фраз типа:
    # вещество абляционного следа
    # первое слово уже может быть главным существительным в именительном падеже.
    # Тогда не надо превращать фразу в "вещество абляционный след".
    head_index: int | None = None

    for index, (_word, parsed) in enumerate(parsed_words):
        if parsed is not None and parsed.tag.POS == "NOUN" and "nomn" in parsed.tag:
            head_index = index
            break

    if head_index is None:
        for index in range(len(parsed_words) - 1, -1, -1):
            _word, parsed = parsed_words[index]

            if parsed is not None and parsed.tag.POS == "NOUN":
                head_index = index
                break

    if head_index is None:
        return value

    head_word, head_parsed = parsed_words[head_index]

    if head_parsed is None:
        return value

    head_nominative = head_parsed if "nomn" in head_parsed.tag else head_parsed.inflect({"nomn"})

    if head_nominative is None:
        return value

    head_number = "plur" if "plur" in head_nominative.tag else "sing"

    head_gender = None

    if head_number == "sing":
        for gender in ("masc", "femn", "neut"):
            if gender in head_nominative.tag:
                head_gender = gender
                break

    result: list[str] = []

    for index, (word, parsed) in enumerate(parsed_words):
        if parsed is None:
            result.append(word)
            continue

        if index == head_index:
            result.append(head_nominative.word)
            continue

        # Прилагательные перед главным существительным согласуем с ним:
        # абляционного следа -> абляционный след
        # витимского метеороида -> витимский метеороид
        # снегового покрова -> снеговой покров
        if parsed.tag.POS in {"ADJF", "PRTF"} and index < head_index:
            grammemes = {"nomn", head_number}

            if head_gender is not None:
                grammemes.add(head_gender)

            inflected = parsed.inflect(grammemes)

            if inflected is not None:
                result.append(inflected.word)
                continue

        # Остальные существительные не всегда надо трогать.
        # Например:
        # вещество абляционного следа
        # Здесь "вещество" уже в именительном, а "следа" — зависимое слово.
        # Поэтому не склоняем всё подряд.
        result.append(word)

    phrase = " ".join(result)
    return _format_ru_phrase_case(phrase)


def _format_ru_phrase_case(value: str) -> str:
    words = value.split()

    if not words:
        return value

    formatted: list[str] = []

    for index, word in enumerate(words):
        parsed = _best_morph_parse(word) if re.search(r"[А-Яа-яЁё]", word) else None

        if index == 0 or (parsed is not None and "Geox" in parsed.tag):
            formatted.append(word[:1].upper() + word[1:])
        else:
            formatted.append(word)

    return " ".join(formatted)

def _format_phrase(value: str, *, language: str | None) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .;,:")

    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", value))

    if language == "ru" or has_cyrillic:
        return _to_nominative_ru_phrase(value.lower())

    return value.lower()


def _dedupe_phrases(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        value = _clean_metadata_line(value)

        if _is_bad_formatted_phrase(value):
            continue

        cleaned = value.lower().replace("ё", "е")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if not cleaned:
            continue

        if cleaned in seen:
            continue

        seen.add(cleaned)
        result.append(value.strip())

    return result


def _extract_frequent_phrases(
    text: str,
    *,
    title: str | None,
    language: str | None,
    limit: int,
    min_frequency: int = 2,
) -> list[str]:
    meaningful_text = _extract_meaningful_metadata_text(text, limit=30000)

    segments = _phrase_token_segments(meaningful_text)

    if not segments:
        return []

    title_token_set = set(_phrase_tokens(title or ""))
    counts: Counter[str] = Counter()

    for tokens in segments:
        if len(tokens) < 2:
            continue

        for ngram_size in (2, 3):
            if len(tokens) < ngram_size:
                continue

            for index in range(0, len(tokens) - ngram_size + 1):
                ngram = tuple(tokens[index:index + ngram_size])

                if not _is_good_phrase_tokens(ngram):
                    continue

                counts[" ".join(ngram)] += 1

    scored: list[tuple[float, str]] = []

    for phrase, count in counts.items():
        phrase_tokens = set(phrase.split())
        title_bonus = len(phrase_tokens & title_token_set) * 1.5

        if count < min_frequency and title_bonus == 0:
            continue

        score = count * len(phrase.split()) + title_bonus
        scored.append((score, phrase))

    scored.sort(key=lambda item: (-item[0], item[1]))

    phrases = [
        _format_phrase(phrase, language=language)
        for _score, phrase in scored[: limit * 4]
    ]

    return _dedupe_phrases(phrases)[:limit]


def _extract_keywords_from_focused_text(
    text: str,
    *,
    title: str | None,
    language: str | None,
) -> list[str]:
    focused_text = "\n".join(
        [
            title or "",
            _extract_abstract_and_first_paragraphs(text),
        ]
    )

    title_keywords = _extract_title_phrase_seeds(
        title,
        language=language,
        limit=8,
    )

    focused_keywords = _extract_frequent_phrases(
        focused_text,
        title=title,
        language=language,
        limit=10,
        min_frequency=1,
    )

    return _dedupe_phrases([*title_keywords, *focused_keywords])[:10]


def _metadata_title_from_filename(original_name: str | None) -> str | None:
    """
    Мягкий вариант title из имени файла только для keywords/topics.

    Важно: это НЕ основной title публикации. Здесь можно использовать даже
    техническое имя вида ``027_rannekembriyskiy_vysokokalievy_m.pdf`` как
    дополнительную подсказку для ключевых слов, потому что раньше это давало
    более стабильные темы, чем частотный анализ всего PDF.
    """

    candidate = _filename_title_candidate(original_name)

    if not candidate:
        return None

    candidate = re.sub(r"^\s*\d{1,4}[-_\s]+", "", candidate)
    candidate = re.sub(r"\b(?:article|file|document|scan|paper|pdf)\s*\d*\b", " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s+", " ", candidate).strip(" -–—_.")

    if len(candidate) < 8:
        return None

    return candidate


def _select_keyword_seed_title(
    *,
    title: str | None,
    title_confidence: str,
    filename_metadata_title: str | None,
) -> str | None:
    """
    Выбирает безопасный текст-источник для автопредложений keywords/topics.

    Не используем весь PDF как источник по умолчанию: из него часто вылезают
    организации, названия сборников, сноски, соседние статьи и случайные n-grams.
    """

    if title and title_confidence in {"high", "medium"} and not _is_bad_extracted_title(title):
        return title

    if filename_metadata_title:
        return filename_metadata_title

    if title and not _is_bad_extracted_title(title):
        return title

    return None


def _extract_keywords_from_title_source(
    title_source: str | None,
    *,
    language: str | None,
) -> list[str]:
    """
    Консервативная генерация keywords: только из title/filename.

    Это намеренно проще, чем частотный анализ всего PDF. Для MVP лучше получить
    3–8 проверяемых подсказок, чем много мусора из текста статьи.
    """

    if not title_source:
        return []

    return _dedupe_phrases(
        _extract_title_phrase_seeds(
            title_source,
            language=language,
            limit=10,
        )
    )[:8]


def _extract_topics_from_keywords(
    *,
    title: str | None,
    keywords: list[str],
) -> list[str]:
    haystack = " ".join([title or "", *keywords]).lower().replace("ё", "е")

    if not haystack:
        return []

    scored: list[tuple[int, int, str]] = []

    for order, (topic, markers) in enumerate(TOPIC_RULES):
        score = sum(1 for marker in markers if marker in haystack)

        if score:
            scored.append((score, -order, topic))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))

    topics = [topic for _score, _order, topic in scored]
    return _dedupe_phrases(topics)[:5]


def _extract_keywords(text: str) -> list[str]:
    lines = _extract_metadata_lines(text)
    raw_parts: list[str] = []
    collecting = False

    for line in lines:
        low = line.lower()

        if not collecting:
            match = re.search(
                r"(?:keywords|key\s*words|ключевые\s+слова)\s*(?::|—|-)?\s*(.*)",
                line,
                re.IGNORECASE,
            )

            if match is None:
                continue

            collecting = True
            rest = match.group(1).strip()

            if rest:
                raw_parts.append(rest)

            continue

        if (
            SECTION_START_RE.search(line)
            or line.startswith("*")
            or re.match(
                r"^(for citation|to cite|recommended by|received|accepted|published|1\.)",
                low,
            )
            or AFFILIATION_RE.search(line)
        ):
            break

        # Если пошел обычный длинный абзац, значит блок ключевых слов закончился.
        if len(line) > 180 and not re.search(r";|,", line):
            break

        raw_parts.append(line)

    if not raw_parts:
        return []

    raw_keywords = " ".join(raw_parts)
    raw_keywords = re.sub(r"\s+", " ", raw_keywords)

    items = re.split(r";|,|•|\|", raw_keywords)

    keywords: list[str] = []
    seen: set[str] = set()

    for item in items:
        keyword = _clean_metadata_line(item)

        if len(keyword) < 2:
            continue

        if _is_bad_formatted_phrase(keyword):
            continue

        if SECTION_START_RE.search(keyword) or BAD_TITLE_RE.search(keyword):
            continue

        if len(keyword) > 90:
            continue

        if len(keyword.split()) > 6:
            continue

        if "." in keyword and not re.search(
            r"\b[A-ZА-ЯЁ]\.\s*[A-ZА-ЯЁ]\.",
            keyword,
        ):
            continue

        if re.search(r"(19\d{2}|20\d{2})", keyword):
            continue

        if re.match(r"^\d", keyword):
            continue

        if re.search(
            r"refers to|both by|gillespie|batbaatar",
            keyword,
            re.IGNORECASE,
        ):
            continue

        if _line_looks_like_author_list(keyword):
            continue

        if re.search(r"[А-ЯЁA-Z]{3,}\s+[А-ЯЁA-Z]{3,}", keyword):
            continue

        if keyword.lower().startswith(("in ", "both ", "such ", "however ")):
            continue

        normalized = keyword.lower().replace("ё", "е")

        if "ivanov" in normalized or "иванов" in normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)

        # Если ключевое слово русское — тоже приводим к именительному падежу.
        keyword = _format_phrase(keyword, language=_detect_language(keyword))
        keywords.append(keyword)

    return keywords[:12]


def _merge_unique_values(*groups: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for value in group:
            value = _clean_metadata_line(str(value))

            if not value:
                continue

            key = value.lower().replace("\u0451", "\u0435")

            if key in seen:
                continue

            seen.add(key)
            result.append(value)

            if limit is not None and len(result) >= limit:
                return result

    return result


def _normalize_ai_authors(authors: list[str]) -> list[str]:
    result: list[str] = []

    for author in authors:
        normalized_authors = _extract_authors_from_lines([author])

        if normalized_authors:
            result.extend(normalized_authors)
            continue

        normalized = format_author_display_name(author)

        if normalized is not None:
            result.append(normalized)

    return _merge_unique_values(result)


def _normalize_ai_keywords(
    keywords: list[str],
    *,
    language: str | None,
) -> list[str]:
    formatted: list[str] = []

    for keyword in keywords:
        keyword = _clean_metadata_line(keyword)

        if not keyword:
            continue

        if len(keyword) > 90 or len(keyword.split()) > 6:
            continue

        if _is_bad_formatted_phrase(keyword):
            continue

        formatted.append(_format_phrase(keyword, language=language))

    return _dedupe_phrases(formatted)


def _ai_field_confidence(analysis, field_name: str, default: float = 0.0) -> float:
    metadata = analysis.field_metadata.get(field_name)

    if metadata is None or metadata.confidence is None:
        return default

    return metadata.confidence


def _merge_ai_list_if_confident(
    current_values: list[str],
    ai_values: list[str],
    *,
    confidence: float,
    prefer_ai_threshold: float,
    limit: int | None = None,
) -> list[str]:
    if confidence >= prefer_ai_threshold:
        return _merge_unique_values(ai_values, current_values, limit=limit)

    return _merge_unique_values(current_values, ai_values, limit=limit)


def _merge_ai_publication_analysis(
    extracted: ExtractedPublicationMetadata,
    *,
    full_text: str,
    filename_title: str | None,
    original_filename: str | None = None,
) -> ExtractedPublicationMetadata:
    analysis_mode = settings.ai_publication_analysis_mode.strip().lower()

    if analysis_mode not in {"always", "fallback"}:
        return extracted

    if analysis_mode == "fallback" and not _needs_ai_publication_analysis(extracted):
        return extracted

    analysis_text = _extract_meaningful_metadata_text(full_text, limit=16000)
    analysis = analyze_publication_text(
        analysis_text,
        filename=original_filename,
    )

    if analysis is None:
        return extracted

    title = extracted.title
    title_source = extracted.title_source
    title_confidence = extracted.title_confidence
    title_warning = extracted.title_warning
    ai_title = _clean_metadata_line(analysis.title or "")

    if (
        ai_title
        and not _is_bad_extracted_title(ai_title)
        and _ai_field_confidence(analysis, "title", default=0.8) >= 0.65
        and (
            not title
            or title_confidence == "low"
            or title_source == "filename"
        )
    ):
        title = ai_title
        title_source = "ai"
        title_confidence = "medium"
        title_warning = None

    year = extracted.year

    if year is None and _ai_field_confidence(analysis, "year", default=0.8) >= 0.6:
        year = analysis.year

    doi = extracted.doi

    if doi is None and _ai_field_confidence(analysis, "doi", default=0.8) >= 0.7:
        doi = analysis.doi

    language = extracted.language or _detect_language(
        full_text,
        ai_title or filename_title,
    )

    ai_authors = _normalize_ai_authors(analysis.authors)
    authors = _merge_ai_list_if_confident(
        extracted.authors,
        ai_authors,
        confidence=_ai_field_confidence(analysis, "authors", default=0.8),
        prefer_ai_threshold=0.75,
    )

    ai_keywords = _normalize_ai_keywords(analysis.keywords, language=language)
    keywords = _merge_ai_list_if_confident(
        extracted.keywords,
        ai_keywords,
        confidence=_ai_field_confidence(analysis, "keywords", default=0.8),
        prefer_ai_threshold=0.7,
        limit=12,
    )
    keywords = _filter_author_phrases(keywords, authors)

    topic_seed_title = title or filename_title
    inferred_topics = _extract_topics_from_keywords(
        title=topic_seed_title,
        keywords=keywords,
    )
    topics = _merge_unique_values(inferred_topics, extracted.topics, limit=5)

    return ExtractedPublicationMetadata(
        title=title,
        year=year,
        language=language,
        publication_type=extracted.publication_type,
        doi=doi,
        authors=authors,
        keywords=keywords,
        topics=topics,
        title_source=title_source,
        title_confidence=title_confidence,
        title_warning=title_warning,
    )


def _needs_ai_publication_analysis(
    extracted: ExtractedPublicationMetadata,
) -> bool:
    """Use the 7B model only when the lightweight parser needs help."""
    title_needs_help = (
        not extracted.title
        or extracted.title_confidence == "low"
        or extracted.title_source == "filename"
    )

    return (
        title_needs_help
        or extracted.year is None
        or not extracted.authors
        or not extracted.keywords
    )


def extract_publication_metadata_from_pdf(
    file_path: Path | str,
    original_name: str | None = None,
) -> ExtractedPublicationMetadata:
    file_path = Path(file_path)
    original_filename = original_name or file_path.name
    filename_title = _filename_title_candidate(original_filename)
    filename_title_quality = _filename_title_quality(
        filename_title,
        raw_title=Path(original_filename).stem,
    )
    pages = _extract_pages(file_path)

    full_text = "\n".join(page.text for page in pages)

    if not full_text.strip():
        title, title_source, title_confidence, title_warning = _select_title(
            None,
            filename_title=filename_title,
            filename_quality=filename_title_quality,
        )
        extracted = ExtractedPublicationMetadata(
            title=title,
            year=None,
            language=None,
            publication_type="article",
            doi=None,
            authors=[],
            keywords=[],
            topics=[],
            title_source=title_source,
            title_confidence=title_confidence,
            title_warning=title_warning,
        )
        return extracted

    kind = _detect_document_kind(full_text)

    title_match = _extract_title(
        pages,
        kind=kind,
        filename_title=filename_title if filename_title_quality >= 3 else None,
        allow_filename_fallback=False,
    )

    title, title_source, title_confidence, title_warning = _select_title(
        title_match,
        filename_title=filename_title,
        filename_quality=filename_title_quality,
    )
    language = _detect_language(full_text, filename_title)

    authors = _extract_authors(
        pages,
        title_match=title_match,
        kind=kind,
    )

    explicit_keywords = _extract_keywords(full_text)
    filename_metadata_title = _metadata_title_from_filename(original_filename)
    keyword_seed_title = _select_keyword_seed_title(
        title=title,
        title_confidence=title_confidence,
        filename_metadata_title=filename_metadata_title,
    )

    if explicit_keywords:
        # Если в PDF есть явный блок "Ключевые слова" / "Keywords", доверяем ему.
        # Не смешиваем его с частотными фразами из текста, чтобы не засорять результат.
        keywords = _dedupe_phrases(explicit_keywords)[:12]
    else:
        # Без явного блока берём только title/filename как источник подсказок.
        # Полнотекстовый frequent extraction временно отключён: он давал много мусора
        # из организаций, сборников, сносок, таблиц и соседних статей.
        keywords = _extract_keywords_from_title_source(
            keyword_seed_title,
            language=language,
        )

    keywords = _filter_author_phrases(keywords, authors)

    topics = _extract_topics_from_keywords(
        title=keyword_seed_title,
        keywords=keywords,
    )

    extracted = ExtractedPublicationMetadata(
        title=title,
        year=_extract_year(full_text, filename_title),
        language=language,
        publication_type="article",
        doi=_extract_doi(full_text),
        authors=authors,
        keywords=keywords,
        topics=topics,
        title_source=title_source,
        title_confidence=title_confidence,
        title_warning=title_warning,
    )

    return _merge_ai_publication_analysis(
        extracted,
        full_text=full_text,
        filename_title=filename_title,
        original_filename=original_filename,
    )


def extract_publication_metadata_from_bytes(
    content: bytes,
    original_name: str | None = None,
) -> ExtractedPublicationMetadata:
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")

    with NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
        temporary_file.write(content)
        temporary_path = Path(temporary_file.name)

    try:
        extracted = extract_publication_metadata_from_pdf(
            temporary_path,
            original_name=original_name,
        )

        return extracted

    finally:
        temporary_path.unlink(missing_ok=True)

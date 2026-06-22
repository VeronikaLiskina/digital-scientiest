from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
import re
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.source_file import SourceFile
from app.utils.file_hash import calculate_file_hash

try:
    import pymorphy3
except ImportError:
    pymorphy3 = None


MORPH = pymorphy3.MorphAnalyzer() if pymorphy3 is not None else None

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
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
}

EN_STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "into", "onto",
    "after", "before", "between", "within", "without", "were", "was", "are", "is", "has", "have",
    "had", "can", "may", "also", "such", "however", "therefore", "using", "based", "study",
    "studies", "article", "paper", "results", "data", "sample", "samples", "table", "figure",
    "fig", "shown", "obtained", "analysis", "analyses", "content", "contents", "value", "values",
}

PHRASE_BAD_WORDS_RE = re.compile(
    r"(abstract|keywords|introduction|references|copyright|license|citation|"
    r"аннотация|ключевые\s+слова|введение|список\s+литературы|литература|"
    r"поступило|представлено|таблица|рисунок|рис\.|"
    r"доклады\s+академии\s+наук|академии\s+наук|"
    r"сибирского\s+отделения|российской\s+академии\s+наук)",
    re.IGNORECASE,
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




@dataclass
class ExtractedPublicationMetadata:
    title: str | None
    year: int | None
    language: str | None
    publication_type: str | None
    doi: str | None
    authors: list[str]
    keywords: list[str]
    topics: list[str]


@dataclass
class PageText:
    number: int
    text: str
    lines: list[str]


@dataclass
class TitleMatch:
    title: str
    page_index: int
    line_index: int | None
    score: int


def validate_pdf_upload(file: UploadFile) -> str:
    original_name = file.filename or "publication.pdf"
    file_extension = Path(original_name).suffix.lower()

    if file_extension != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed",
        )

    return original_name


def save_pdf_content(original_name: str, content: bytes) -> Path:
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_name = f"{uuid4()}.pdf"
    saved_path = upload_dir / saved_name
    saved_path.write_bytes(content)

    return saved_path


async def find_source_file_by_hash(
    db: AsyncSession,
    file_hash: str,
) -> SourceFile | None:
    result = await db.execute(
        select(SourceFile).where(SourceFile.file_hash == file_hash)
    )
    return result.scalar_one_or_none()


async def save_uploaded_pdf_as_source_file(
    db: AsyncSession,
    file: UploadFile,
    *,
    comment: str | None = None,
    fail_on_duplicate: bool = True,
) -> tuple[SourceFile, bool]:
    original_name = validate_pdf_upload(file)
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")

    file_hash = calculate_file_hash(content)
    existing_file = await find_source_file_by_hash(db, file_hash)

    if existing_file is not None:
        if fail_on_duplicate:
            raise HTTPException(
                status_code=409,
                detail="Такой PDF уже загружался",
            )

        return existing_file, True

    saved_path = save_pdf_content(original_name, content)

    source_file = SourceFile(
        file_name=original_name,
        file_path=str(saved_path),
        file_type="application/pdf",
        file_hash=file_hash,
        pdf_quality="text_pdf",
        has_figures=False,
        has_tables=False,
        processing_status="new",
        comment=comment,
    )

    db.add(source_file)
    await db.flush()

    return source_file, False


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
    reader = PdfReader(str(file_path))
    pages: list[PageText] = []

    for page_index, page in enumerate(reader.pages):
        if page_index >= max_pages:
            break

        text = _clean_text(page.extract_text() or "")
        pages.append(
            PageText(
                number=page_index,
                text=text,
                lines=_extract_metadata_lines(text),
            )
        )

    return pages


def _filename_title(original_name: str | None) -> str | None:
    if not original_name:
        return None

    title = Path(original_name).stem
    title = re.sub(r"\s*\(\d+\)\s*$", "", title)
    title = re.sub(r"[_]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—")

    # Частый случай: "Geological Journal - 2018 - Sheth - Title"
    journal_match = re.search(r"-\s*[A-ZА-ЯЁ][^-]{20,}$", title)
    if title.lower().startswith("geological journal") and journal_match:
        title = journal_match.group(0).strip(" -")

    if len(title) < 8:
        return None

    return title


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


def _title_token_overlap(title: str | None, filename_title: str | None) -> int:
    if not title or not filename_title:
        return 0

    filename_tokens = set(_title_tokens(filename_title)[:10])
    title_tokens = set(_title_tokens(title))
    return len(filename_tokens & title_tokens)


def _should_prefer_filename_title(
    extracted_title: str | None,
    filename_title: str | None,
) -> bool:
    if not filename_title:
        return False

    if not extracted_title:
        return True

    if _is_bad_extracted_title(extracted_title):
        return True

    filename_tokens = _title_tokens(filename_title)[:10]
    overlap = _title_token_overlap(extracted_title, filename_title)

    # В корпусе русские файлы обычно названы самим заголовком статьи.
    # PDF-текст часто выдает битую строку с номером страницы или частью абзаца,
    # поэтому для длинного осмысленного русского имени файла оно надежнее.
    if re.search(r"[А-Яа-яЁё]", filename_title) and len(filename_tokens) >= 4:
        return True

    if len(filename_tokens) >= 3 and overlap < 2:
        return True

    low = extracted_title.lower()
    if low.startswith(("research article", "article", "central asian orogenic belt")):
        return True

    if re.search(r"\b(ivan koulakov|mingqi liu|taras gerya|andrey jakovlev)\b", low):
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
    author_like_hits = len(_find_author_candidates(cleaned))
    return author_like_hits > 0


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


def _extract_patent_title(lines: list[str], page_index: int, filename_title: str | None) -> TitleMatch | None:
    for index, line in enumerate(lines):
        if "(54)" in line:
            title = line.split("(54)", 1)[-1].strip(" .:-")
            if not title and index + 1 < len(lines):
                title = lines[index + 1]
            title = _normalize_title(title)
            if title:
                return TitleMatch(title=title, page_index=page_index, line_index=index, score=18)

    if filename_title:
        return TitleMatch(title=filename_title, page_index=page_index, line_index=None, score=14)

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
) -> TitleMatch | None:
    if kind == "mdpi":
        mdpi_title = _extract_mdpi_title(page.lines, page.number)
        if mdpi_title is not None:
            return mdpi_title

    if kind == "patent":
        patent_title = _extract_patent_title(page.lines, page.number, filename_title)
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
) -> TitleMatch | None:
    preferred_page = _find_page_by_filename_title(pages, filename_title)

    # Для больших сборников имя файла обычно и есть название нужной статьи.
    # Не пытаемся брать первый попавшийся заголовок из сборника — это часто чужая статья.
    if kind == "conference_collection" and filename_title:
        page_index = preferred_page if preferred_page is not None else 0
        line_index = None

        if preferred_page is not None and preferred_page < len(pages):
            line_index = _find_title_line_index(pages[preferred_page], filename_title)

        return TitleMatch(
            title=filename_title,
            page_index=page_index,
            line_index=line_index,
            score=16 if preferred_page is not None else 10,
        )

    ordered_pages = pages
    if preferred_page is not None:
        ordered_pages = sorted(
            pages,
            key=lambda page: 0 if page.number == preferred_page else 1 + page.number,
        )

    best_match: TitleMatch | None = None

    for page in ordered_pages:
        title = _extract_title_from_page(page, kind=kind, filename_title=filename_title)
        if title is None:
            continue

        if best_match is None or title.score > best_match.score:
            best_match = title

    if _should_prefer_filename_title(
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
        )

    return best_match

def _normalize_author_source(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", value)
    value = re.sub(r"\b([A-ZА-ЯЁ])\.([A-ZА-ЯЁ])\.", r"\1. \2.", value)
    value = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+", "", value)
    value = re.sub(r"\d+", "", value)
    value = value.replace("*", " ").replace("†", " ").replace("‡", " ")
    value = value.replace("|", ",")
    value = re.sub(r"\band\b", ",", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .;,:")


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


def _normalize_initial(value: str) -> str:
    value = value.strip(" .")
    if not value:
        return ""

    initial = value[:1].upper()
    initial = LATIN_INITIAL_TO_RU.get(initial, initial)
    return f"{initial}."


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


def format_author_display_name(raw_name: str) -> str | None:
    """
    Приводит автора к виду Иванов А.В.

    Важно: имена не угадываем.
    Alexei V. Ivanov -> Иванов А.В. только потому, что в строке уже есть A. и V.
    A. V. Ivanov -> Иванов А.В.
    Ivanov A. V. -> Иванов А.В.
    Иванов Алексей Викторович -> Иванов А.В.
    """

    cleaned = _normalize_author_source(raw_name)

    if not cleaned or AUTHOR_BAD_WORDS_RE.search(cleaned) or AFFILIATION_RE.search(cleaned):
        return None

    alias_key = _make_author_alias_key(cleaned)
    if alias_key in AUTHOR_ALIASES:
        return AUTHOR_ALIASES[alias_key]

    # Иванов Алексей Викторович / Иванов Алексей В.
    match = re.fullmatch(
        r"([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ][а-яё-]+)(?:\s+([А-ЯЁ][а-яё-]+|[А-ЯЁ]\.?))?",
        cleaned,
    )
    if match:
        last_name, first_name, patronymic = match.groups()
        return _format_author_canonical(last_name, first_name, patronymic)

    # А. В. Иванов / A. V. Ivanov
    match = re.fullmatch(
        r"([A-ZА-ЯЁ])\.\s*([A-ZА-ЯЁ])\.\s*([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+)",
        cleaned,
    )
    if match:
        first_initial, second_initial, last_name = match.groups()
        return _format_author_canonical(last_name, first_initial, second_initial)

    # Иванов А. В. / Ivanov A. V.
    match = re.fullmatch(
        r"([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+)\s+([A-ZА-ЯЁ])\.\s*([A-ZА-ЯЁ])\.?",
        cleaned,
    )
    if match:
        last_name, first_initial, second_initial = match.groups()
        return _format_author_canonical(last_name, first_initial, second_initial)

    # Alexei V. Ivanov
    match = re.fullmatch(
        r"([A-Z][a-zA-Z'’\-ÿ]+)\s+([A-Z])\.\s*([A-Z][a-zA-Z'’\-]+)",
        cleaned,
    )
    if match:
        first_name, middle_initial, last_name = match.groups()
        return _format_author_canonical(last_name, first_name, middle_initial)

    # Alexei Ivanov — второго инициала нет, поэтому НЕ угадываем отчество.
    # Такой вариант лучше не автозаполнять как автора, чем записать неполное ФИО.
    if re.fullmatch(
        r"[A-Z][a-zA-Z'’\-ÿ]+\s+[A-Z][a-zA-Z'’\-]+",
        cleaned,
    ):
        return None

    # Если распарсить не смогли, не выдумываем.
    return None


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

    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text))

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

    if AUTHOR_BAD_WORDS_RE.search(value) or AFFILIATION_RE.search(value) or DOI_RE.search(value):
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


def _normalize_author_list(candidates: list[str]) -> list[str]:
    authors: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        normalized_author = normalize_author_display_name(candidate)
        if not normalized_author:
            continue

        normalized_author = format_author_display_name(normalized_author) or normalized_author

        key = _make_author_alias_key(normalized_author)
        if key in seen:
            continue

        seen.add(key)
        authors.append(normalized_author)

    return authors[:15]


def _clean_author_line(line: str) -> str:
    line = _clean_metadata_line(line)

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
    return line.strip(" .;,:—-–")


def _should_stop_author_block(line: str) -> bool:
    low_line = line.lower().strip()

    if not low_line:
        return False

    if SECTION_START_RE.search(line):
        return True

    if AFFILIATION_RE.search(line):
        return True

    if low_line.startswith((
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


def _extract_authors_from_lines(lines: list[str]) -> list[str]:
    cleaned_lines = [_clean_author_line(line) for line in lines]
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
            if "©" not in line and not re.search(r"\b(19\d{2}|20\d{2})\s*г\.", line):
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

    page = pages[title_match.page_index]
    start = (title_match.line_index or 0) + 1
    section_index = _find_first_section_index(page.lines)

    # В старых PDF pypdf часто ставит title/authors после основного текста.
    # Тогда section_index может оказаться меньше start. В таком случае
    # нельзя обрезать блок по section_index.
    if section_index <= start:
        end = min(len(page.lines), start + 30)
    else:
        end = min(section_index, start + 30)

    block: list[str] = []

    for line in page.lines[start:end]:
        if _should_stop_author_block(line):
            break

        if BAD_TITLE_RE.search(line) and "©" not in line:
            continue

        cleaned_line = _clean_author_line(line)

        if cleaned_line:
            block.append(cleaned_line)

    return _extract_authors_from_lines(block)


def _extract_authors_from_citation(full_text: str) -> list[str]:
    citation_match = re.search(
        r"(?:Citation:|To cite this article:)\s*(.+?)(?:\(\d{4}\)|\.\s+[A-ZА-ЯЁ]|https?://|DOI|$)",
        full_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if citation_match is None:
        return []

    return _normalize_author_list(_find_author_candidates(citation_match.group(1)))


def _extract_authors_from_first_pages(pages: list[PageText]) -> list[str]:
    # Последний fallback. Берём больше строк, потому что pypdf может поставить
    # заголовок и авторов ближе к 70–100 строке первой страницы.
    first_lines: list[str] = []

    for page in pages[:2]:
        first_lines.extend(page.lines[:140])

    return _extract_authors_from_lines(first_lines)


def _extract_authors(
    pages: list[PageText],
    *,
    title_match: TitleMatch | None,
    kind: str,
) -> list[str]:
    full_text = "\n".join(page.text for page in pages)

    if title_match is not None and "флотилия плавучих" in title_match.title.lower():
        return []

    extractors = []

    if kind == "patent":
        extractors.append(lambda: _extract_patent_authors(full_text))

    # 1. Старые русские журналы: блок после © 2004 г.
    extractors.append(lambda: _extract_authors_from_copyright_block(pages))

    # 2. Зона после найденного заголовка.
    if not (
        kind == "conference_collection"
        and (title_match is None or title_match.line_index is None)
    ):
        extractors.append(lambda: _extract_authors_from_title_zone(
            pages,
            title_match=title_match,
        ))

    # 3. Citation / To cite this article.
    extractors.append(lambda: _extract_authors_from_citation(full_text))

    # 4. Fallback по первым страницам.
    if not (
        title_match is not None
        and title_match.line_index is None
        and re.search(r"[А-Яа-яЁё]", title_match.title)
        and title_match.score <= 8
    ):
        extractors.append(lambda: _extract_authors_from_first_pages(pages))

    best_authors: list[str] = []

    for extractor in extractors:
        authors = extractor()

        if len(authors) > len(best_authors):
            best_authors = authors

        # 2+ автора уже достаточно для большинства статей,
        # но если нашли 5+, почти наверняка это полный блок.
        if len(best_authors) >= 5:
            break

    return best_authors[:15]


def _extract_text_before_references(text: str) -> str:
    match = re.search(
        r"\n\s*(?:references|список\s+литературы|литература)\b",
        text,
        flags=re.IGNORECASE,
    )

    if match is None:
        return text

    return text[:match.start()]


def _phrase_tokens(text: str) -> list[str]:
    normalized = text.lower().replace("ё", "е")
    return re.findall(r"[a-zа-я][a-zа-я\-]{2,}", normalized)


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

    if PHRASE_BAD_WORDS_RE.search(phrase):
        return False

    return True
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

        parsed = MORPH.parse(cleaned_word)[0]
        parsed_words.append((cleaned_word, parsed))

    # Ищем главное существительное.
    # Обычно оно последнее:
    # абляционного следа -> следа
    # витимского метеороида -> метеороида
    # снегового покрова -> покрова
    head_index: int | None = None

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

    head_nominative = head_parsed.inflect({"nomn"})

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
    return phrase[:1].upper() + phrase[1:] if phrase else phrase

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
        cleaned = _clean_metadata_line(value).lower().replace("ё", "е")
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
    meaningful_text = _extract_text_before_references(text)
    meaningful_text = meaningful_text[:30000]

    tokens = _phrase_tokens(meaningful_text)

    if len(tokens) < 20:
        return []

    title_token_set = set(_phrase_tokens(title or ""))
    counts: Counter[str] = Counter()

    for ngram_size in (2, 3):
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
        for _score, phrase in scored[: limit * 3]
    ]

    return _dedupe_phrases(phrases)[:limit]


def _extract_keywords_from_frequency(
    text: str,
    *,
    title: str | None,
    language: str | None,
) -> list[str]:
    return _extract_frequent_phrases(
        text,
        title=title,
        language=language,
        limit=10,
        min_frequency=2,
    )


def _extract_topics_from_frequency(
    text: str,
    *,
    title: str | None,
    language: str | None,
    keywords: list[str],
) -> list[str]:
    # Для тем важнее не весь текст, а title + keywords + верхняя часть статьи.
    # Так меньше шансов получить случайные технические пары из таблиц и списка литературы.
    focused_text = "\n".join(
        [
            title or "",
            " ".join(keywords),
            _extract_text_before_references(text)[:12000],
        ]
    )

    return _extract_frequent_phrases(
        focused_text,
        title=title,
        language=language,
        limit=7,
        min_frequency=2,
    )


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


def extract_publication_metadata_from_pdf(
    file_path: Path,
    original_name: str | None = None,
) -> ExtractedPublicationMetadata:
    filename_title = _filename_title(original_name or file_path.name)
    pages = _extract_pages(file_path)

    full_text = "\n".join(page.text for page in pages)

    if not full_text.strip():
        return ExtractedPublicationMetadata(
            title=filename_title,
            year=None,
            language=None,
            publication_type="article",
            doi=None,
            authors=[],
            keywords=[],
            topics=[],
        )

    kind = _detect_document_kind(full_text)

    title_match = _extract_title(
        pages,
        kind=kind,
        filename_title=filename_title,
    )

    title = title_match.title if title_match is not None else filename_title
    language = _detect_language(full_text, filename_title)

    authors = _extract_authors(
        pages,
        title_match=title_match,
        kind=kind,
    )

    explicit_keywords = _extract_keywords(full_text)

    generated_keywords = _extract_keywords_from_frequency(
        full_text,
        title=title,
        language=language,
    )

    keywords = _dedupe_phrases(
        [*explicit_keywords, *generated_keywords]
    )[:12]

    topics = _extract_topics_from_frequency(
        full_text,
        title=title,
        language=language,
        keywords=keywords,
    )

    return ExtractedPublicationMetadata(
        title=title,
        year=_extract_year(full_text, filename_title),
        language=language,
        publication_type="article",
        doi=_extract_doi(full_text),
        authors=authors,
        keywords=keywords,
        topics=topics,
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
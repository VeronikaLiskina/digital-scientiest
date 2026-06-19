from dataclasses import dataclass
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


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
KEYWORDS_RE = re.compile(
    r"(?:keywords|ключевые\s+слова)\s*[:—-]\s*"
    r"(.+?)"
    r"(?:\n\s*(?:1\.|introduction|введение|abstract|аннотация|references|список литературы)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
SECTION_START_RE = re.compile(
    r"^(abstract|аннотация|keywords|ключевые\s+слова|1\.\s*introduction|введение)\b",
    re.IGNORECASE,
)
BAD_TITLE_RE = re.compile(
    r"(doi|issn|isbn|удк|journal|volume|vol\.|issue|received|accepted|published|"
    r"copyright|license|university|университет|институт|conference|proceedings|"
    r"citation|editor|редакц|поступила|принята)",
    re.IGNORECASE,
)
AFFILIATION_RE = re.compile(
    r"(university|institute|department|faculty|laboratory|school|college|"
    r"университет|институт|кафедра|факультет|лаборатория|школа|колледж|"
    r"@|http|www\.)",
    re.IGNORECASE,
)


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


def _extract_first_pages_text(file_path: Path, max_pages: int = 2) -> str:
    reader = PdfReader(str(file_path))
    page_texts: list[str] = []

    for page_index, page in enumerate(reader.pages):
        if page_index >= max_pages:
            break
        page_texts.append(page.extract_text() or "")

    return "\n".join(page_texts)


def _clean_metadata_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line)
    return line.strip(" \t\n\r.;,")


def _extract_metadata_lines(text: str) -> list[str]:
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = _clean_metadata_line(raw_line)

        if len(line) < 3:
            continue

        lines.append(line)

    return lines


def _find_first_section_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if SECTION_START_RE.search(line):
            return index

    return min(len(lines), 30)


def _detect_language(text: str) -> str | None:
    cyrillic_count = len(re.findall(r"[а-яА-Я]", text))
    latin_count = len(re.findall(r"[a-zA-Z]", text))

    if cyrillic_count == 0 and latin_count == 0:
        return None

    return "ru" if cyrillic_count > latin_count else "en"


def _extract_doi(text: str) -> str | None:
    match = DOI_RE.search(text)
    if match is None:
        return None

    return match.group(0).rstrip(".,);]")


def _extract_year(text: str) -> int | None:
    years = [int(match.group(1)) for match in YEAR_RE.finditer(text)]

    if not years:
        return None

    valid_years = [year for year in years if 1900 <= year <= 2100]
    return valid_years[0] if valid_years else None


def _score_title_candidate(line: str, index: int) -> int:
    normalized = line.strip().lower()
    score = 0

    if 20 <= len(line) <= 250:
        score += 4

    if index <= 10:
        score += 3
    elif index <= 20:
        score += 1

    if len(line.split()) >= 4:
        score += 2

    if BAD_TITLE_RE.search(line):
        score -= 8

    if DOI_RE.search(line):
        score -= 10

    if "@" in line:
        score -= 10

    if re.fullmatch(r"\d{4}", normalized):
        score -= 10

    if len(line) > 250:
        score -= 5

    return score


def _extract_title(lines: list[str]) -> tuple[str | None, int | None]:
    section_start_index = _find_first_section_index(lines)
    candidates: list[tuple[int, int, str]] = []

    for index, line in enumerate(lines[:section_start_index]):
        score = _score_title_candidate(line, index)

        if score > 0:
            candidates.append((score, index, line))

    if not candidates:
        return None, None

    best_score, best_index, best_line = max(
        candidates,
        key=lambda item: item[0],
    )

    # Если уверенность низкая, лучше оставить поле пустым,
    # чем автоматически подставить мусор из PDF.
    if best_score < 5:
        return None, None

    return best_line, best_index


AUTHOR_NAME_PATTERNS = [
    # Иванов И.И.
    re.compile(r"^[А-ЯЁ][а-яё-]+\\s+[А-ЯЁ]\\.\\s*[А-ЯЁ]\\.?$"),

    # Иванов И. И.
    re.compile(r"^[А-ЯЁ][а-яё-]+\\s+[А-ЯЁ]\\.\\s+[А-ЯЁ]\\.?$"),

    # Иванов Алексей Викторович
    re.compile(r"^[А-ЯЁ][а-яё-]+\\s+[А-ЯЁ][а-яё-]+(?:\\s+[А-ЯЁ][а-яё-]+)?$"),

    # E. I. Dementerova
    re.compile(r"^[A-Z]\\.\\s*[A-Z]\\.\\s*[A-Z][a-zA-Z-]+$"),

    # E.I. Dementerova
    re.compile(r"^[A-Z]\\.[A-Z]\\.\\s*[A-Z][a-zA-Z-]+$"),

    # Ivan Petrov / Ivan A. Petrov
    re.compile(r"^[A-Z][a-zA-Z-]+\\s+(?:[A-Z]\\.\\s+)?[A-Z][a-zA-Z-]+$"),
]


AUTHOR_BAD_WORDS_RE = re.compile(
    r"(rocks|mafic|archean|paleoarchean|siberian|craton|article|abstract|"
    r"keywords|introduction|journal|university|institute|department|"
    r"породы|архей|кратон|аннотация|ключевые слова|введение|"
    r"университет|институт|кафедра|факультет)",
    re.IGNORECASE,
)


def _looks_like_author(value: str) -> bool:
    value = _clean_metadata_line(value)

    if len(value) < 3:
        return False

    # Слишком длинное — почти точно не автор
    if len(value) > 60:
        return False

    words = value.split()

    # У автора обычно 2–4 части, а не длинное предложение
    if len(words) > 4:
        return False

    # Строка капсом и длинная — часто это название статьи
    if value.isupper() and len(value) > 20:
        return False

    # Email, ссылки, организации
    if AFFILIATION_RE.search(value):
        return False

    if DOI_RE.search(value):
        return False

    # Слова, характерные для названий/организаций, а не авторов
    if AUTHOR_BAD_WORDS_RE.search(value):
        return False

    return any(pattern.match(value) for pattern in AUTHOR_NAME_PATTERNS)


def _extract_authors(
    lines: list[str],
    title_index: int | None,
) -> list[str]:
    if title_index is None:
        return []

    section_start_index = _find_first_section_index(lines)

    # Авторы чаще всего идут сразу после названия и до Abstract/Keywords.
    # Берём только первые несколько строк, чтобы не захватить организации.
    author_zone = lines[title_index + 1:section_start_index][:5]

    raw_authors = " ".join(author_zone)
    raw_authors = re.sub(r"\d+|\*|†|‡|§", " ", raw_authors)
    raw_authors = re.sub(r"\s+", " ", raw_authors)

    parts = re.split(r";|,|\band\b|\bи\b", raw_authors)

    authors: list[str] = []
    seen: set[str] = set()

    for part in parts:
        author = _clean_metadata_line(part)

        if not _looks_like_author(author):
            continue

        normalized = author.lower().replace("ё", "е")

        if normalized in seen:
            continue

        seen.add(normalized)
        authors.append(author)

    return authors[:12]


def _extract_keywords(text: str) -> list[str]:
    match = KEYWORDS_RE.search(text)

    if match is None:
        return []

    raw_keywords = match.group(1)
    raw_keywords = re.sub(r"\s+", " ", raw_keywords)
    raw_keywords = re.split(r";|,|•|\|", raw_keywords)

    keywords: list[str] = []
    seen: set[str] = set()

    for item in raw_keywords:
        keyword = _clean_metadata_line(item)

        if len(keyword) < 2:
            continue

        normalized = keyword.lower().replace("ё", "е")

        if normalized in seen:
            continue

        seen.add(normalized)
        keywords.append(keyword)

    return keywords[:10]


def extract_publication_metadata_from_pdf(file_path: Path) -> ExtractedPublicationMetadata:
    text = _extract_first_pages_text(file_path)

    if not text.strip():
        return ExtractedPublicationMetadata(
            title=None,
            year=None,
            language=None,
            publication_type="article",
            doi=None,
            authors=[],
            keywords=[],
            topics=[],
        )

    lines = _extract_metadata_lines(text)
    title, title_index = _extract_title(lines)
    authors = _extract_authors(lines, title_index)
    keywords = _extract_keywords(text)

    return ExtractedPublicationMetadata(
        title=title,
        year=_extract_year(text),
        language=_detect_language(text),
        publication_type="article",
        doi=_extract_doi(text),
        authors=authors,
        keywords=keywords,
        topics=[],
    )


def extract_publication_metadata_from_bytes(content: bytes) -> ExtractedPublicationMetadata:
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")

    with NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
        temporary_file.write(content)
        temporary_path = Path(temporary_file.name)

    try:
        return extract_publication_metadata_from_pdf(temporary_path)
    finally:
        temporary_path.unlink(missing_ok=True)

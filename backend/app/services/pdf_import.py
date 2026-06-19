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
    r"(?:keywords|ключевые\s+слова)\s*[:—-]\s*(.+?)(?:\n\s*\d+\.|\n\s*(?:introduction|введение)\b|\n\s*abstract\b|$)",
    re.IGNORECASE | re.DOTALL,
)
AUTHOR_STOP_WORDS = {
    "abstract",
    "keywords",
    "аннотация",
    "ключевые слова",
    "introduction",
    "введение",
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

    # Обычно год публикации находится среди первых совпадений.
    valid_years = [year for year in years if 1900 <= year <= 2100]
    return valid_years[0] if valid_years else None


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


def _looks_like_title(line: str) -> bool:
    lower = line.lower()

    if len(line) < 12:
        return False

    if any(stop_word in lower for stop_word in AUTHOR_STOP_WORDS):
        return False

    if DOI_RE.search(line):
        return False

    if re.search(r"^(journal|volume|issue|issn|удк|doi)\b", lower):
        return False

    return True


def _extract_title_and_authors(text: str) -> tuple[str | None, list[str]]:
    lines = [
        _clean_metadata_line(line)
        for line in text.splitlines()
        if _clean_metadata_line(line)
    ]

    title_index: int | None = None
    title: str | None = None

    for index, line in enumerate(lines[:25]):
        if _looks_like_title(line):
            title_index = index
            title = line
            break

    if title_index is None:
        return None, []

    author_lines: list[str] = []

    for line in lines[title_index + 1:title_index + 5]:
        lower = line.lower()

        if any(stop_word in lower for stop_word in AUTHOR_STOP_WORDS):
            break

        if DOI_RE.search(line) or YEAR_RE.search(line):
            continue

        if len(line) > 180:
            continue

        # Авторские строки часто содержат запятые, инициалы или несколько ФИО.
        if re.search(r"[А-ЯA-Z][а-яa-z]+", line):
            author_lines.append(line)

    raw_authors = " ".join(author_lines)
    raw_authors = re.sub(r"\d+|\*|†|‡|§", " ", raw_authors)
    raw_authors = re.sub(r"\s+", " ", raw_authors)

    authors: list[str] = []
    seen: set[str] = set()

    for item in re.split(r";|,|\band\b|\bи\b", raw_authors):
        author = _clean_metadata_line(item)

        if len(author) < 3:
            continue

        if "@" in author:
            continue

        normalized = author.lower().replace("ё", "е")

        if normalized in seen:
            continue

        seen.add(normalized)
        authors.append(author)

    return title, authors[:12]


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

    title, authors = _extract_title_and_authors(text)

    return ExtractedPublicationMetadata(
        title=title,
        year=_extract_year(text),
        language=_detect_language(text),
        publication_type="article",
        doi=_extract_doi(text),
        authors=authors,
        keywords=_extract_keywords(text),
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


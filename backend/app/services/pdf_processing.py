import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.models.processing_log import ProcessingLog
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.services.embedding_service import EmbeddingService


MAX_CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150


SKIP_SECTIONS = {
    "References",
    "Back matter",
}


NOISE_PATTERNS = [
    r"^Minerals\s+2024,\s+14,\s+1158\s+\d+\s+of\s+\d+",
    r"^Minerals\s+2024,\s+14,\s+x\s+FOR\s+PEER\s+REVIEW",
    r"^https?://",
    r"^Citation:",
    r"^Academic Editors:",
    r"^Received:",
    r"^Revised:",
    r"^Accepted:",
    r"^Published:",
    r"^Copyright:",
    r"^Licensee",
    r"^This article is an open access",
    r"^distributed under",
    r"^conditions of the Creative Commons",
    r"^Disclaimer/Publisher",
    # журнальные колонтитулы
    r"^\w+\s+\d{4},\s*\d+",
    r"^\d+\s+of\s+\d+$",
    r"^ДОКЛАДЫ\s+АКАДЕМИИ\s+НАУК",
    r"^ГЕОЛОГИЯ\s+И\s+ГЕОФИЗИКА",
    r"^ОТЕЧЕСТВЕННАЯ\s+ГЕОЛОГИЯ",
]


SECTION_PATTERNS = [
    (r"^Abstract:?", "Abstract"),
    (r"^Keywords:?", "Keywords"),
    (r"^1\.\s+Introduction", "1. Introduction"),
    (r"^2\.\s+Geological Characteristics", "2. Geological Characteristics of the Deposits"),
    (r"^3\.\s+Methods", "3. Methods"),
    (r"^4\.\s+Results", "4. Results"),
    (r"^5\.\s+Discussion", "5. Discussion"),
    (r"^6\.\s+Conclusions", "6. Conclusions"),
    (r"^Supplementary Materials:", "Back matter"),
    (r"^Author Contributions:", "Back matter"),
    (r"^Funding:", "Back matter"),
    (r"^Data Availability Statement:", "Back matter"),
    (r"^Conflicts of Interest:", "Back matter"),
    (r"^References\b", "References"),
    (r"^Аннотация:?", "Аннотация"),

    (r"^Key\s+words:?", "Keywords"),
    (r"^Ключевые\s+слова:?", "Ключевые слова"),

    (r"^1\.\s+Введение", "1. Введение"),
    (r"^Введение\b", "Введение"),

    (r"^Методы\b", "Методы"),
    (r"^Материалы\s+и\s+методы\b", "Материалы и методы"),
    (r"^Результаты\b", "Результаты"),
    (r"^Обсуждение\b", "Обсуждение"),
    (r"^Заключение\b", "Заключение"),
    (r"^Выводы\b", "Выводы"),

    (r"^Список\s+литературы\b", "References"),
    (r"^Литература\b", "References"),
]


SECTION_MARKERS = [
    "Abstract:",
    "Keywords:",
    "1. Introduction",
    "2. Geological Characteristics",
    "3. Methods",
    "4. Results",
    "5. Discussion",
    "6. Conclusions",
    "Supplementary Materials:",
    "Author Contributions:",
    "Funding:",
    "Data Availability Statement:",
    "Conflicts of Interest:",
    "References",
]


@dataclass
class TextBlock:
    page_number: int
    section_title: str
    text: str


@dataclass
class ChunkPayload:
    chunk_text: str
    page_number: int
    chunk_index: int


def add_section_breaks(text: str) -> str:
    """
    Иногда pypdf извлекает заголовок раздела в той же строке,
    что и предыдущий текст.

    Например:
    Keywords: ... 1. Introduction Determining...

    Поэтому перед известными заголовками добавляем перенос строки.
    """

    for marker in SECTION_MARKERS:
        escaped_marker = re.escape(marker)
        text = re.sub(
            rf"\s+({escaped_marker})",
            r"\n\1",
            text,
            flags=re.IGNORECASE,
        )

    return text


def detect_section_title(line: str) -> str | None:
    for pattern, section_title in SECTION_PATTERNS:
        if re.search(pattern, line, flags=re.IGNORECASE):
            return section_title

    return None


def clean_text_for_postgres(text: str | None) -> str:
    if not text:
        return ""

    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0B\x0C\x0E-\x1F]", " ", text)

    return text.strip()


def clean_pdf_text(text: str) -> str:
    """
    Простая очистка мусора после извлечения текста из PDF.

    Для MVP:
    - убираем служебные строки журнала;
    - убираем FOR PEER REVIEW;
    - убираем повторяющиеся футеры/ссылки;
    - склеиваем переносы слов;
    - нормализуем пробелы;
    - добавляем переносы перед заголовками разделов.
    """
    from app.utils.pdf_text import normalize_pdf_text

    if not text:
        return ""

    text = normalize_pdf_text(text)

    # Удаляем мягкий перенос
    text = text.replace("\u00ad", "")

    # В этом PDF pypdf может извлекать букву "t" как спецсимвол.
    # Поэтому не удаляем символ, а заменяем на "t".
    text = text.replace("\ufffe", "t")
    text = text.replace("￾", "t")

    # Склейка слов, разорванных переносом:
    # mineralisa-
    # tion -> mineralisation
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)

    # Убираем частые ссылочные/служебные URL
    text = re.sub(
        r"https://doi\.org/10\.3390/\s*min14111158",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"https://www\.mdpi\.com/journal/minerals",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # Добавляем переносы перед заголовками разделов
    text = add_section_breaks(text)

    cleaned_lines: list[str] = []
    seen_short_lines: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        is_noise = any(
            re.search(pattern, line, flags=re.IGNORECASE)
            for pattern in NOISE_PATTERNS
        )

        if is_noise:
            continue

        # Убираем короткие дубли.
        # Например, повторяющиеся заголовки, футеры, подписи.
        if len(line) < 90:
            normalized_line = line.lower()

            if normalized_line in seen_short_lines:
                continue

            seen_short_lines.add(normalized_line)

        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # Нормализация пробелов
    text = re.sub(r"[ \t]+", " ", text)

    # Нормализация пустых строк
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_page_into_blocks(
    page_number: int,
    page_text: str,
    current_section: str,
) -> tuple[list[TextBlock], str]:
    """
    Делим текст страницы на блоки по разделам статьи.

    Это не идеальный научный парсер, но для MVP нормально:
    - Abstract будет отдельно;
    - Keywords отдельно;
    - Introduction отдельно;
    - Methods/Results/Discussion/Conclusions отдельно.
    """

    lines = [line.strip() for line in page_text.splitlines() if line.strip()]

    blocks: list[TextBlock] = []
    buffer: list[str] = []
    section_title = current_section

    for line in lines:
        detected_section = detect_section_title(line)

        if detected_section is not None:
            if buffer and section_title not in SKIP_SECTIONS:
                blocks.append(
                    TextBlock(
                        page_number=page_number,
                        section_title=section_title,
                        text="\n".join(buffer),
                    )
                )

            section_title = detected_section
            buffer = []

        if section_title in SKIP_SECTIONS:
            continue

        buffer.append(line)

    if buffer and section_title not in SKIP_SECTIONS:
        blocks.append(
            TextBlock(
                page_number=page_number,
                section_title=section_title,
                text="\n".join(buffer),
            )
        )

    return blocks, section_title


def extract_text_blocks(file_path: Path) -> list[TextBlock]:
    reader = PdfReader(str(file_path))

    text_blocks: list[TextBlock] = []
    current_section = "Metadata"

    for page_index, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        cleaned_text = clean_pdf_text(raw_text)

        if not cleaned_text:
            continue

        page_blocks, current_section = split_page_into_blocks(
            page_number=page_index,
            page_text=cleaned_text,
            current_section=current_section,
        )

        text_blocks.extend(page_blocks)

    return text_blocks


def find_chunk_end(text: str, start: int, max_size: int) -> int:
    """
    Ищем более аккуратное место для конца чанка.
    Сначала пытаемся закончить на конце предложения.
    Если не получилось — хотя бы на пробеле.
    """

    hard_end = min(start + max_size, len(text))

    if hard_end >= len(text):
        return len(text)

    min_end = start + int(max_size * 0.6)

    sentence_end = text.rfind(". ", min_end, hard_end)

    if sentence_end != -1:
        return sentence_end + 1

    semicolon_end = text.rfind("; ", min_end, hard_end)

    if semicolon_end != -1:
        return semicolon_end + 1

    space_end = text.rfind(" ", min_end, hard_end)

    if space_end != -1:
        return space_end

    return hard_end


def split_text_into_chunks(text: str) -> list[str]:
    text = " ".join(text.split())

    if not text:
        return []

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = find_chunk_end(
            text=text,
            start=start,
            max_size=MAX_CHUNK_SIZE,
        )

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(end - CHUNK_OVERLAP, start + 1)

    return chunks


def build_chunk_text(
    section_title: str,
    page_number: int,
    chunk_text: str,
) -> str:
    return (
        f"[section: {section_title}]\n"
        f"[page: {page_number}]\n"
        f"{chunk_text}"
    )


def make_chunk_fingerprint(text: str) -> str:
    """
    Нужен для простой дедупликации почти одинаковых чанков.

    Берем начало текста, нормализуем пробелы и регистр.
    Для MVP этого достаточно.
    """

    normalized_text = " ".join(text.lower().split())
    return normalized_text[:500]


async def add_processing_log(
    db: AsyncSession,
    source_file_id: int,
    step_name: str,
    status: str,
    error_message: str | None = None,
) -> None:
    log = ProcessingLog(
        source_file_id=source_file_id,
        step_name=step_name,
        status=status,
        error_message=error_message,
    )

    db.add(log)
    await db.commit()


async def process_pdf_file(
    db: AsyncSession,
    source_file_id: int,
    embedding_service: EmbeddingService,
) -> dict:
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise ValueError("Source file not found")

    file_path = Path(source_file.file_path)

    if not file_path.exists():
        source_file.processing_status = "error"

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            step_name="file_check",
            status="error",
            error_message="File not found on server",
        )

        await db.commit()
        raise ValueError("File not found on server")

    publication_result = await db.execute(
        select(Publication).where(
            Publication.source_file_id == source_file_id
        )
    )
    publication = publication_result.scalar_one_or_none()

    if publication is None:
        source_file.processing_status = "requires_review"

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            step_name="publication_check",
            status="error",
            error_message="Publication card is not linked to this source file",
        )

        await db.commit()
        raise ValueError("Сначала создайте карточку публикации для этого файла")

    try:
        source_file.processing_status = "processing"
        await db.commit()

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            step_name="file_check",
            status="success",
        )

        text_blocks = extract_text_blocks(file_path)

        if not text_blocks:
            source_file.processing_status = "error"

            await add_processing_log(
                db=db,
                source_file_id=source_file_id,
                step_name="text_extraction",
                status="error",
                error_message="Text was not extracted from PDF",
            )

            await db.commit()
            raise ValueError("Не удалось извлечь текст из PDF")

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            step_name="text_extraction",
            status="success",
        )

        chunk_payloads: list[ChunkPayload] = []
        seen_fingerprints: set[str] = set()
        chunk_index = 0

        for block in text_blocks:
            chunks = split_text_into_chunks(block.text)

            for raw_chunk_text in chunks:
                chunk_text = build_chunk_text(
                    section_title=block.section_title,
                    page_number=block.page_number,
                    chunk_text=raw_chunk_text,
                )
                chunk_text = clean_text_for_postgres(chunk_text)

                if not chunk_text:
                    continue

                fingerprint = make_chunk_fingerprint(chunk_text)

                if fingerprint in seen_fingerprints:
                    continue

                seen_fingerprints.add(fingerprint)

                chunk_payloads.append(
                    ChunkPayload(
                        chunk_text=chunk_text,
                        page_number=block.page_number,
                        chunk_index=chunk_index,
                    )
                )

                chunk_index += 1

        if not chunk_payloads:
            source_file.processing_status = "error"

            await add_processing_log(
                db=db,
                source_file_id=source_file_id,
                step_name="chunking",
                status="error",
                error_message="No chunks were created",
            )

            await db.commit()
            raise ValueError("Не удалось создать чанки из PDF")

        # Перезапись чанков.
        # Если публикация уже была обработана,
        # старые document_chunks удаляются,
        # а новые создаются заново.
        chunk_texts = [chunk.chunk_text for chunk in chunk_payloads]

        embeddings = await asyncio.to_thread(
            embedding_service.embed_texts,
            chunk_texts,
        )

        if len(embeddings) != len(chunk_payloads):
            source_file.processing_status = "error"

            await add_processing_log(
                db=db,
                source_file_id=source_file_id,
                step_name="embedding",
                status="error",
                error_message="Embedding count does not match chunk count",
            )

            await db.commit()
            raise ValueError("Embedding count does not match chunk count")

        embedded_at = datetime.now(timezone.utc)

        new_chunks = [
            DocumentChunk(
                publication_id=publication.id,
                chunk_text=chunk.chunk_text,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                embedding=embedding,
                embedding_model=embedding_service.model_name,
                embedded_at=embedded_at,
            )
            for chunk, embedding in zip(chunk_payloads, embeddings)
        ]

        await db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.publication_id == publication.id
            )
        )

        db.add_all(new_chunks)
        await db.commit()

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            step_name="chunking",
            status="success",
        )

        source_file.processing_status = "processed"
        await db.commit()

        return {
            "source_file_id": source_file_id,
            "publication_id": publication.id,
            "chunks_created": len(new_chunks),
            "status": "processed",
        }

    except Exception as exc:
        await db.rollback()

        source_file = await db.get(SourceFile, source_file_id)

        if source_file is not None:
            source_file.processing_status = "error"

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            step_name="processing",
            status="error",
            error_message=str(exc),
        )

        raise

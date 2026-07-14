import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies import get_embedding_service
from app.models.source_file import SourceFile
from app.schemas.source_file import (
    CatalogMatchRead,
    ExtractedPublicationMetadataRead,
    SourceFileCreate,
    SourceFileMetadataPreview,
    SourceFileRead,
    SourceFileUpdate,
)
from app.services.embedding_service import EmbeddingService
from app.services.metadata_matcher import (
    CatalogMatchResult,
    match_existing_authors,
    match_existing_keywords,
    match_existing_topics,
)
from app.services.pdf_import import (
    extract_publication_metadata_from_bytes,
    extract_publication_metadata_from_pdf,
    find_source_file_by_hash,
    save_uploaded_pdf_as_source_file,
    validate_pdf_upload,
)
from app.services.pdf_processing import process_pdf_file
from app.services.pdf_processing_queue import enqueue_pdf_processing
from app.services.publication_cleanup_service import delete_managed_upload_file
from app.services.topic_suggester import suggest_topic_names
from app.utils.file_hash import calculate_file_hash


router = APIRouter(prefix="/source-files", tags=["Source files"])
logger = logging.getLogger(__name__)


def _metadata_extraction_error_message(exc: Exception) -> str:
    """Return a useful explanation without losing the original error reason."""
    reason = " ".join(str(exc).split()).strip()
    reason_lower = reason.lower()

    if any(marker in reason_lower for marker in ("password", "decrypt", "encrypted")):
        explanation = "PDF защищён паролем или запрещает извлечение текста."
    elif any(marker in reason_lower for marker in ("ocr", "tesseract", "text layer")):
        explanation = (
            "В PDF не найден пригодный текстовый слой, а распознавание скана (OCR) "
            "не завершилось."
        )
    elif any(marker in reason_lower for marker in ("eof", "xref", "invalid pdf", "pdf header")):
        explanation = "PDF повреждён или имеет неподдерживаемую структуру."
    else:
        explanation = "Во время чтения PDF произошла ошибка."

    if reason:
        return f"{explanation} Техническая причина: {reason[:500]}"

    return explanation


def _merge_names(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        value = value.strip()

        if not value:
            continue

        key = value.lower().replace("ё", "е")

        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result


def _to_catalog_match_reads(result: CatalogMatchResult) -> list[CatalogMatchRead]:
    return [
        CatalogMatchRead(
            id=item.id,
            name=item.name,
            extracted_name=item.extracted_name,
        )
        for item in result.matches
    ]


async def _build_metadata_preview(
    db: AsyncSession,
    *,
    file_hash: str,
    extracted,
    embedding_service=None,
) -> SourceFileMetadataPreview:
    existing_topic_suggestions = await suggest_topic_names(
        db=db,
        title=extracted.title,
        keywords=extracted.keywords,
        embedding_service=embedding_service,
    )

    extracted.topics = _merge_names(
        [*existing_topic_suggestions, *extracted.topics]
    )[:5]

    author_match_result = await match_existing_authors(db, extracted.authors)
    keyword_match_result = await match_existing_keywords(db, extracted.keywords)
    topic_match_result = await match_existing_topics(db, extracted.topics)

    return SourceFileMetadataPreview(
        status="metadata_extracted",
        file_hash=file_hash,
        review_status="needs_review",
        extracted=ExtractedPublicationMetadataRead(
            title=extracted.title,
            title_source=extracted.title_source,
            title_confidence=extracted.title_confidence,
            title_warning=extracted.title_warning,
            year=extracted.year,
            language=extracted.language,
            publication_type=extracted.publication_type,
            doi=extracted.doi,
            authors=extracted.authors,
            keywords=extracted.keywords,
            topics=extracted.topics,
            matched_authors=_to_catalog_match_reads(author_match_result),
            matched_author_ids=[item.id for item in author_match_result.matches],
            new_authors=author_match_result.new_names,
            matched_keywords=_to_catalog_match_reads(keyword_match_result),
            matched_keyword_ids=[item.id for item in keyword_match_result.matches],
            new_keywords=keyword_match_result.new_names,
            matched_topics=_to_catalog_match_reads(topic_match_result),
            matched_topic_ids=[item.id for item in topic_match_result.matches],
            new_topics=topic_match_result.new_names,
        ),
    )


@router.post("", response_model=SourceFileRead, status_code=status.HTTP_201_CREATED)
async def create_source_file(
    data: SourceFileCreate,
    db: AsyncSession = Depends(get_db),
):
    source_file = SourceFile(**data.model_dump())

    db.add(source_file)
    await db.commit()
    await db.refresh(source_file)

    return source_file


@router.post("/upload", response_model=SourceFileRead, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    source_file, _ = await save_uploaded_pdf_as_source_file(
        db=db,
        file=file,
        comment="Файл загружен вручную",
        fail_on_duplicate=True,
    )

    await db.commit()
    await db.refresh(source_file)

    return source_file


@router.post("/extract-metadata", response_model=SourceFileMetadataPreview)
async def extract_pdf_metadata(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Предпросмотр данных из PDF для существующей формы создания публикации.

    Endpoint не сохраняет файл и не создает публикацию.
    Он только:
    - проверяет PDF;
    - считает hash;
    - предупреждает о дубле PDF;
    - пытается вытащить title/year/language/doi/authors/keywords/topics;
    - ищет соответствия в уже существующих авторах, ключевых словах и темах;
    - возвращает id найденных записей, чтобы frontend мог сразу отметить их в форме.
    """

    validate_pdf_upload(file)
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")

    file_hash = calculate_file_hash(content)
    existing_file = await find_source_file_by_hash(db, file_hash)

    if existing_file is not None:
        return SourceFileMetadataPreview(
            status="duplicate_file",
            file_hash=file_hash,
            review_status="blocked",
            duplicate_source_file_id=existing_file.id,
            message=(
                "Такой PDF уже загружался. Выберите его из списка уже "
                "загруженных файлов или загрузите другой PDF."
            ),
            extracted=None,
        )

    try:
        extracted = await asyncio.to_thread(
            extract_publication_metadata_from_bytes,
            content,
            original_name=file.filename,
        )
    except Exception as exc:
        logger.exception(
            "Failed to extract publication metadata from PDF %r (hash=%s)",
            file.filename,
            file_hash,
        )
        return SourceFileMetadataPreview(
            status="metadata_error",
            file_hash=file_hash,
            review_status="manual_entry",
            message=_metadata_extraction_error_message(exc),
            extracted=None,
        )

    if extracted is None:
        return SourceFileMetadataPreview(
            status="metadata_error",
            file_hash=file_hash,
            review_status="manual_entry",
            message="PDF выбран, но метаданные не были извлечены.",
            extracted=None,
        )

    return await _build_metadata_preview(
        db,
        file_hash=file_hash,
        extracted=extracted,
        embedding_service=None,
    )


@router.get("", response_model=list[SourceFileRead])
async def get_source_files(
    processing_status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(SourceFile).order_by(SourceFile.id.desc())

    if processing_status:
        query = query.where(SourceFile.processing_status == processing_status)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{source_file_id}", response_model=SourceFileRead)
async def get_source_file(
    source_file_id: int,
    db: AsyncSession = Depends(get_db),
):
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    return source_file


@router.post("/{source_file_id}/extract-metadata", response_model=SourceFileMetadataPreview)
async def extract_stored_pdf_metadata(
    source_file_id: int,
    db: AsyncSession = Depends(get_db),
):
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    file_path = Path(source_file.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    preview_file_hash = source_file.file_hash or calculate_file_hash(
        file_path.read_bytes()
    )

    try:
        extracted = await asyncio.to_thread(
            extract_publication_metadata_from_pdf,
            file_path,
            original_name=source_file.file_name,
        )
    except Exception as exc:
        logger.exception(
            "Failed to extract publication metadata from stored PDF %s (%r)",
            source_file.id,
            source_file.file_name,
        )
        return SourceFileMetadataPreview(
            status="metadata_error",
            file_hash=preview_file_hash,
            review_status="manual_entry",
            message=_metadata_extraction_error_message(exc),
            extracted=None,
        )

    return await _build_metadata_preview(
        db,
        file_hash=preview_file_hash,
        extracted=extracted,
        embedding_service=None,
    )


@router.get("/{source_file_id}/download")
async def download_source_file(
    source_file_id: int,
    db: AsyncSession = Depends(get_db),
):
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    file_path = Path(source_file.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(
        path=file_path,
        media_type=source_file.file_type,
        filename=source_file.file_name,
    )


@router.post("/{source_file_id}/process")
async def process_source_file(
    source_file_id: int,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    try:
        result = await process_pdf_file(
            db=db,
            source_file_id=source_file_id,
            embedding_service=embedding_service,
        )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@router.post("/{source_file_id}/process/start", status_code=status.HTTP_202_ACCEPTED)
async def start_source_file_processing(
    source_file_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        processing_status = await enqueue_pdf_processing(db, source_file_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Source file not found")

    return {
        "source_file_id": source_file_id,
        "status": processing_status,
    }


@router.patch("/{source_file_id}", response_model=SourceFileRead)
async def update_source_file(
    source_file_id: int,
    data: SourceFileUpdate,
    db: AsyncSession = Depends(get_db),
):
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(source_file, field, value)

    await db.commit()
    await db.refresh(source_file)

    return source_file


@router.delete("/{source_file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_file(
    source_file_id: int,
    db: AsyncSession = Depends(get_db),
):
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    file_path = source_file.file_path
    await db.delete(source_file)
    await db.commit()
    delete_managed_upload_file(file_path)

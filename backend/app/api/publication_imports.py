from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.models.publication_import import ImportBatch, ImportItem
from app.models.source_file import SourceFile
from app.schemas.publication_import import ImportBatchRead, ImportItemRead
from app.schemas.source_file import CatalogMatchRead, ExtractedPublicationMetadataRead
from app.services.embedding_service import EmbeddingService
from app.services.metadata_matcher import (
    CatalogMatchResult,
    match_existing_authors,
    match_existing_keywords,
    match_existing_topics,
)
from app.services.pdf_import import (
    extract_publication_metadata_from_pdf,
    find_source_file_by_hash,
    save_pdf_content,
    validate_pdf_upload,
)
from app.services.topic_suggester import suggest_topic_names
from app.utils.file_hash import calculate_file_hash

router = APIRouter(prefix="/publication-imports", tags=["Publication imports"])

MAX_IMPORT_FILES = 20
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_BATCH_SIZE_BYTES = 300 * 1024 * 1024


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


def _batch_load_options():
    return (selectinload(ImportBatch.items),)


def _item_to_read(item: ImportItem) -> ImportItemRead:
    extracted = None
    if item.extracted_metadata_json:
        extracted = ExtractedPublicationMetadataRead(**item.extracted_metadata_json)

    return ImportItemRead(
        id=item.id,
        batch_id=item.batch_id,
        source_file_id=item.source_file_id,
        publication_id=item.publication_id,
        original_file_name=item.original_file_name,
        status=item.status,
        error_message=item.error_message,
        extracted_metadata=extracted,
        title=item.title,
        title_source=item.title_source,
        title_confidence=item.title_confidence,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _batch_to_read(batch: ImportBatch) -> ImportBatchRead:
    items = sorted(batch.items, key=lambda item: item.id)
    return ImportBatchRead(
        id=batch.id,
        status=batch.status,
        total_files=batch.total_files,
        processed_count=batch.processed_count,
        needs_review_count=batch.needs_review_count,
        saved_count=batch.saved_count,
        duplicate_count=batch.duplicate_count,
        error_count=batch.error_count,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        items=[_item_to_read(item) for item in items],
    )


def _recalculate_batch(batch: ImportBatch, items: list[ImportItem]) -> None:
    batch.total_files = len(items)
    batch.processed_count = len(
        [item for item in items if item.status != "processing"]
    )
    batch.needs_review_count = len(
        [item for item in items if item.status == "needs_review"]
    )
    batch.saved_count = len([item for item in items if item.status == "saved"])
    batch.duplicate_count = len(
        [item for item in items if item.status == "duplicate"]
    )
    batch.error_count = len([item for item in items if item.status == "error"])

    if batch.error_count and not batch.needs_review_count:
        batch.status = "completed_with_errors"
    elif batch.needs_review_count:
        batch.status = "needs_review"
    else:
        batch.status = "completed"


async def _build_extracted_metadata_read(
    db: AsyncSession,
    source_file: SourceFile,
    embedding_service: EmbeddingService | None = None,
) -> ExtractedPublicationMetadataRead:
    extracted = extract_publication_metadata_from_pdf(
        source_file.file_path,
        original_name=source_file.file_name,
    )

    existing_topic_suggestions = await suggest_topic_names(
        db=db,
        title=extracted.title,
        keywords=extracted.keywords,
        embedding_service=embedding_service,
    )
    extracted.topics = _merge_names([*existing_topic_suggestions, *extracted.topics])[:5]

    author_match_result = await match_existing_authors(db, extracted.authors)
    keyword_match_result = await match_existing_keywords(db, extracted.keywords)
    topic_match_result = await match_existing_topics(db, extracted.topics)

    return ExtractedPublicationMetadataRead(
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
    )


async def _process_import_file(
    db: AsyncSession,
    *,
    batch: ImportBatch,
    file: UploadFile,
    content: bytes,
    embedding_service: EmbeddingService | None = None,
) -> ImportItem:
    filename = file.filename or "publication.pdf"
    item = ImportItem(
        batch=batch,
        original_file_name=filename,
        status="processing",
    )
    db.add(item)
    await db.flush()

    try:
        validate_pdf_upload(file)

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise ValueError("Размер PDF превышает лимит 50 МБ")

        file_hash = calculate_file_hash(content)
        existing_file = await find_source_file_by_hash(db, file_hash)

        if existing_file is not None:
            item.source_file_id = existing_file.id
            item.status = "duplicate"
            item.error_message = "Такой файл уже загружен"
            return item

        saved_path = save_pdf_content(filename, content)
        source_file = SourceFile(
            file_name=filename,
            file_path=str(saved_path),
            file_type="application/pdf",
            file_hash=file_hash,
            pdf_quality="text_pdf",
            has_figures=False,
            has_tables=False,
            processing_status="requires_review",
            comment="Файл загружен через массовый импорт PDF",
        )
        db.add(source_file)
        await db.flush()

        item.source_file_id = source_file.id

        extracted_read = await _build_extracted_metadata_read(
            db,
            source_file,
            embedding_service=embedding_service,
        )
        item.extracted_metadata_json = extracted_read.model_dump(mode="json")
        item.title = extracted_read.title
        item.title_source = extracted_read.title_source
        item.title_confidence = extracted_read.title_confidence
        item.status = "needs_review"
        return item

    except Exception as exc:
        item.status = "error"
        item.error_message = str(exc)
        return item


@router.post("", response_model=ImportBatchRead, status_code=status.HTTP_201_CREATED)
async def create_publication_import_batch(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="Выберите PDF-файлы")

    if len(files) > MAX_IMPORT_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"За один раз можно загрузить не больше {MAX_IMPORT_FILES} PDF",
        )

    batch = ImportBatch(status="processing", total_files=len(files))
    db.add(batch)
    await db.flush()

    total_size = 0
    processed_items: list[ImportItem] = []

    for file in files:
        content = await file.read()
        total_size += len(content)

        if total_size > MAX_BATCH_SIZE_BYTES:
            item = ImportItem(
                batch=batch,
                original_file_name=file.filename or "publication.pdf",
                status="error",
                error_message="Общий размер пачки превышает лимит 300 МБ",
            )
            db.add(item)
            processed_items.append(item)
            continue

        processed_items.append(
            await _process_import_file(
                db,
                batch=batch,
                file=file,
                content=content,
            )
        )

    await db.flush()
    _recalculate_batch(batch, processed_items)
    await db.commit()

    result = await db.execute(
        select(ImportBatch)
        .where(ImportBatch.id == batch.id)
        .options(*_batch_load_options())
    )
    return _batch_to_read(result.scalar_one())


@router.get("/{batch_id}", response_model=ImportBatchRead)
async def get_publication_import_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .options(*_batch_load_options())
    )
    batch = result.scalar_one_or_none()

    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")

    return _batch_to_read(batch)


@router.get("/items/{item_id}", response_model=ImportItemRead)
async def get_publication_import_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(ImportItem, item_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Import item not found")

    return _item_to_read(item)

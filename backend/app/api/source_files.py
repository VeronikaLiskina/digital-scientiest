from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.source_file import SourceFile
from app.schemas.source_file import (
    ExtractedPublicationMetadataRead,
    SourceFileCreate,
    SourceFileMetadataPreview,
    SourceFileRead,
    SourceFileUpdate,
)
from app.services.pdf_import import (
    extract_publication_metadata_from_bytes,
    find_source_file_by_hash,
    save_uploaded_pdf_as_source_file,
    validate_pdf_upload,
)
from app.services.pdf_processing import process_pdf_file
from app.services.topic_suggester import suggest_topic_names
from app.utils.file_hash import calculate_file_hash

router = APIRouter(prefix="/source-files", tags=["Source files"])


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

    Важно: endpoint НЕ сохраняет файл и НЕ создает публикацию.
    Он только:
    - проверяет PDF;
    - считает hash;
    - предупреждает о дубле PDF;
    - пытается вытащить title/year/language/doi/authors/keywords;
    - подбирает темы только из существующего справочника topics.
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
            duplicate_source_file_id=existing_file.id,
            message="Такой PDF уже загружался. Выберите его из списка уже загруженных файлов или загрузите другой PDF.",
            extracted=None,
        )

    extracted = extract_publication_metadata_from_bytes(
        content,
        original_name=file.filename,
    )
    extracted.topics = await suggest_topic_names(
        db=db,
        title=extracted.title,
        keywords=extracted.keywords,
    )

    return SourceFileMetadataPreview(
        status="metadata_extracted",
        file_hash=file_hash,
        extracted=ExtractedPublicationMetadataRead(
            title=extracted.title,
            year=extracted.year,
            language=extracted.language,
            publication_type=extracted.publication_type,
            doi=extracted.doi,
            authors=extracted.authors,
            keywords=extracted.keywords,
            topics=extracted.topics,
        ),
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
):
    try:
        result = await process_pdf_file(
            db=db,
            source_file_id=source_file_id,
        )
        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


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

    await db.delete(source_file)
    await db.commit()

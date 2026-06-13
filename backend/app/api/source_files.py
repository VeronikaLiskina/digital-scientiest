from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.models.source_file import SourceFile
from app.schemas.source_file import SourceFileCreate, SourceFileRead, SourceFileUpdate


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
    original_name = file.filename or "publication.pdf"
    file_extension = Path(original_name).suffix.lower()

    if file_extension != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed",
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_name = f"{uuid4()}{file_extension}"
    saved_path = upload_dir / saved_name

    file_content = await file.read()

    with open(saved_path, "wb") as f:
        f.write(file_content)

    source_file = SourceFile(
        file_name=original_name,
        file_path=str(saved_path),
        file_type="application/pdf",
        processing_status="new",
        has_figures=False,
        has_tables=False,
    )

    db.add(source_file)
    await db.commit()
    await db.refresh(source_file)

    return source_file


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
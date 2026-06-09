from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
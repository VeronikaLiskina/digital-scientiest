from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.processing_log import ProcessingLog
from app.models.source_file import SourceFile
from app.schemas.processing_log import (
    ProcessingLogCreate,
    ProcessingLogRead,
    ProcessingLogUpdate,
)


router = APIRouter(prefix="/processing-logs", tags=["Processing logs"])


async def check_source_file_exists(
    db: AsyncSession,
    source_file_id: int,
):
    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=400, detail="Source file not found")


@router.post("", response_model=ProcessingLogRead, status_code=status.HTTP_201_CREATED)
async def create_processing_log(
    data: ProcessingLogCreate,
    db: AsyncSession = Depends(get_db),
):
    await check_source_file_exists(db, data.source_file_id)

    log = ProcessingLog(**data.model_dump())

    db.add(log)
    await db.commit()
    await db.refresh(log)

    return log


@router.get("", response_model=list[ProcessingLogRead])
async def get_processing_logs(
    source_file_id: int | None = Query(default=None),
    publication_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(ProcessingLog).order_by(ProcessingLog.created_at.desc())

    if source_file_id:
        query = query.where(ProcessingLog.source_file_id == source_file_id)

    if publication_id:
        query = query.where(ProcessingLog.publication_id == publication_id)

    if status:
        query = query.where(ProcessingLog.status == status)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{log_id}", response_model=ProcessingLogRead)
async def get_processing_log(
    log_id: int,
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(ProcessingLog, log_id)

    if log is None:
        raise HTTPException(status_code=404, detail="Processing log not found")

    return log


@router.patch("/{log_id}", response_model=ProcessingLogRead)
async def update_processing_log(
    log_id: int,
    data: ProcessingLogUpdate,
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(ProcessingLog, log_id)

    if log is None:
        raise HTTPException(status_code=404, detail="Processing log not found")

    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(log, field, value)

    await db.commit()
    await db.refresh(log)

    return log


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_processing_log(
    log_id: int,
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(ProcessingLog, log_id)

    if log is None:
        raise HTTPException(status_code=404, detail="Processing log not found")

    await db.delete(log)
    await db.commit()
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.schemas.document_chunk import (
    DocumentChunkCreate,
    DocumentChunkRead,
    DocumentChunkUpdate,
)


router = APIRouter(prefix="/document-chunks", tags=["Document chunks"])


async def check_publication_exists(
    db: AsyncSession,
    publication_id: int,
):
    publication = await db.get(Publication, publication_id)

    if publication is None:
        raise HTTPException(status_code=400, detail="Publication not found")


@router.post("", response_model=DocumentChunkRead, status_code=status.HTTP_201_CREATED)
async def create_document_chunk(
    data: DocumentChunkCreate,
    db: AsyncSession = Depends(get_db),
):
    await check_publication_exists(db, data.publication_id)

    chunk = DocumentChunk(**data.model_dump())

    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)

    return chunk


@router.get("", response_model=list[DocumentChunkRead])
async def get_document_chunks(
    publication_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(DocumentChunk).order_by(
        DocumentChunk.publication_id,
        DocumentChunk.chunk_index,
    )

    if publication_id:
        query = query.where(DocumentChunk.publication_id == publication_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{chunk_id}", response_model=DocumentChunkRead)
async def get_document_chunk(
    chunk_id: int,
    db: AsyncSession = Depends(get_db),
):
    chunk = await db.get(DocumentChunk, chunk_id)

    if chunk is None:
        raise HTTPException(status_code=404, detail="Document chunk not found")

    return chunk


@router.patch("/{chunk_id}", response_model=DocumentChunkRead)
async def update_document_chunk(
    chunk_id: int,
    data: DocumentChunkUpdate,
    db: AsyncSession = Depends(get_db),
):
    chunk = await db.get(DocumentChunk, chunk_id)

    if chunk is None:
        raise HTTPException(status_code=404, detail="Document chunk not found")

    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(chunk, field, value)

    await db.commit()
    await db.refresh(chunk)

    return chunk


@router.delete("/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_chunk(
    chunk_id: int,
    db: AsyncSession = Depends(get_db),
):
    chunk = await db.get(DocumentChunk, chunk_id)

    if chunk is None:
        raise HTTPException(status_code=404, detail="Document chunk not found")

    await db.delete(chunk)
    await db.commit()
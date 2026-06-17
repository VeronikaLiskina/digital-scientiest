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
) -> None:
    publication = await db.get(Publication, publication_id)

    if publication is None:
        raise HTTPException(
            status_code=400,
            detail="Publication not found",
        )


async def get_chunk_or_404(
    db: AsyncSession,
    chunk_id: int,
) -> DocumentChunk:
    chunk = await db.get(DocumentChunk, chunk_id)

    if chunk is None:
        raise HTTPException(
            status_code=404,
            detail="Document chunk not found",
        )

    return chunk


@router.post(
    "",
    response_model=DocumentChunkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_chunk(
    data: DocumentChunkCreate,
    db: AsyncSession = Depends(get_db),
):
    await check_publication_exists(db, data.publication_id)

    chunk_text = data.chunk_text.strip()

    if not chunk_text:
        raise HTTPException(
            status_code=400,
            detail="Chunk text cannot be empty",
        )

    chunk_data = data.model_dump()
    chunk_data["chunk_text"] = chunk_text

    chunk = DocumentChunk(**chunk_data)

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

    if publication_id is not None:
        query = query.where(DocumentChunk.publication_id == publication_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{chunk_id}", response_model=DocumentChunkRead)
async def get_document_chunk(
    chunk_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await get_chunk_or_404(db, chunk_id)


@router.patch("/{chunk_id}", response_model=DocumentChunkRead)
async def update_document_chunk(
    chunk_id: int,
    data: DocumentChunkUpdate,
    db: AsyncSession = Depends(get_db),
):
    chunk = await get_chunk_or_404(db, chunk_id)

    update_data = data.model_dump(exclude_unset=True)

    if "publication_id" in update_data:
        await check_publication_exists(db, update_data["publication_id"])

    if "chunk_text" in update_data and update_data["chunk_text"] is not None:
        update_data["chunk_text"] = update_data["chunk_text"].strip()

        if not update_data["chunk_text"]:
            raise HTTPException(
                status_code=400,
                detail="Chunk text cannot be empty",
            )

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
    chunk = await get_chunk_or_404(db, chunk_id)

    await db.delete(chunk)
    await db.commit()
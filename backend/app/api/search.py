import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.dependencies import get_embedding_service
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.services.embedding_service import EmbeddingService


router = APIRouter(prefix="/search", tags=["search"])


@router.get("/semantic")
async def semantic_search(
    query: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    query_embedding = await asyncio.to_thread(
        embedding_service.embed_text,
        query,
    )

    repository = SemanticSearchRepository(session)

    results = await repository.search_chunks(
        query_embedding=query_embedding,
        limit=limit,
    )

    return {
        "query": query,
        "limit": limit,
        "results": results,
    }
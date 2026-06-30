import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies import get_embedding_service
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.services.embedding_service import EmbeddingService


router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/semantic")
async def semantic_search(
    query: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
    min_similarity: float = Query(0.55, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    query_embedding = await asyncio.to_thread(
        embedding_service.embed_text,
        query,
    )

    repository = SemanticSearchRepository(db)

    results = await repository.search_chunks(
        query_embedding=query_embedding,
        limit=limit,
        min_similarity=min_similarity,
    )

    return {
        "query": query,
        "limit": limit,
        "min_similarity": min_similarity,
        "count": len(results),
        "results": results,
    }

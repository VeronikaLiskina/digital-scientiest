import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies import get_embedding_service
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.services.embedding_service import EmbeddingService


router = APIRouter(prefix="/search", tags=["Search"])
logger = logging.getLogger(__name__)


@router.get("/semantic")
async def semantic_search(
    query: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
    min_similarity: float = Query(0.55, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    query_embedding = await asyncio.to_thread(
        embedding_service.embed_query,
        query,
    )

    repository = SemanticSearchRepository(db)

    results = await repository.search_chunks(
        query_embedding=query_embedding,
        embedding_model=embedding_service.model_name,
        query_text=query,
        limit=limit,
        min_similarity=min_similarity,
    )
    logger.info(
        "final_selected_chunks=%s",
        [result.get("chunk_id") for result in results],
    )

    return {
        "query": query,
        "limit": limit,
        "min_similarity": min_similarity,
        "count": len(results),
        "results": results,
    }

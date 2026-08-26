from functools import lru_cache

from app.core.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
        cpu_threads=settings.embedding_cpu_threads,
        max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
    )


@lru_cache
def get_reranker_service() -> RerankerService:
    return RerankerService(
        settings.reranker_model_name,
        batch_size=settings.reranker_batch_size,
        max_length=settings.reranker_max_length,
        min_score=settings.reranker_min_score,
        top_k=settings.reranker_top_k,
        cpu_threads=settings.reranker_cpu_threads,
        max_concurrent_jobs=settings.reranker_max_concurrent_jobs,
    )

from functools import lru_cache
from threading import RLock

from app.core.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService


_model_load_lock = RLock()


def get_embedding_service() -> EmbeddingService:
    # Cold requests can arrive together now that loading runs in a thread.
    # Check the cached factory inside the lock to create only one model.
    with _model_load_lock:
        return _load_embedding_service()


@lru_cache(maxsize=1)
def _load_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
        cpu_threads=settings.embedding_cpu_threads,
        max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
    )


def get_reranker_service() -> RerankerService:
    with _model_load_lock:
        return _load_reranker_service()


@lru_cache(maxsize=1)
def _load_reranker_service() -> RerankerService:
    return RerankerService(
        settings.reranker_model_name,
        batch_size=settings.reranker_batch_size,
        max_length=settings.reranker_max_length,
        min_score=settings.reranker_min_score,
        top_k=settings.reranker_top_k,
        cpu_threads=settings.reranker_cpu_threads,
        max_concurrent_jobs=settings.reranker_max_concurrent_jobs,
    )

from functools import lru_cache

from app.core.config import settings
from app.services.embedding_service import EmbeddingService


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
        cpu_threads=settings.embedding_cpu_threads,
        max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
    )

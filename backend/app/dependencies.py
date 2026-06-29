from functools import lru_cache

from app.core.config import settings
from app.services.embedding_service import EmbeddingService


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(settings.embedding_model_name)
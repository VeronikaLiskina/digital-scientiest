from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.embedding_models import E5_MODEL_NAME, LEGACY_MPNET_MODEL_NAME
from app.services.reranker_service import DEFAULT_RERANKER_MODEL


class Settings(BaseSettings):
    database_url: str
    database_echo: bool = False
    upload_dir: str = "uploads"

    embedding_model_name: str = E5_MODEL_NAME
    embedding_legacy_model_name: str = LEGACY_MPNET_MODEL_NAME
    embedding_dim: int = 768
    embedding_batch_size: int = 16
    embedding_cpu_threads: int = 2
    embedding_max_concurrent_jobs: int = 1
    reranker_model_name: str = DEFAULT_RERANKER_MODEL
    reranker_batch_size: int = 4
    reranker_max_length: int = 1024
    reranker_min_score: float = 0.5
    reranker_top_k: int = 6
    reranker_cpu_threads: int = 2
    reranker_max_concurrent_jobs: int = 1
    celery_broker_url: str = "redis://redis:6379/0"
    pdf_processing_max_retries: int = 3

    llm_provider: Literal["ollama", "groq", "hybrid"] = "ollama"
    hybrid_fallback_delay_seconds: float = 35.0

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:12b"
    ollama_timeout_seconds: int = 120
    ollama_keep_alive: str = "1m"
    ollama_num_ctx: int = 8192
    ollama_think: bool = False

    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: int = 120
    groq_max_completion_tokens: int = 1400
    groq_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    groq_max_retries: int = 1
    ai_publication_analysis_enabled: bool = True
    ai_publication_analysis_mode: str = "fallback"
    ai_publication_analysis_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def active_llm_model(self) -> str:
        if self.llm_provider.strip().lower() == "groq":
            return self.groq_model
        if self.llm_provider.strip().lower() == "hybrid":
            return f"{self.ollama_model} + {self.groq_model}"
        return self.ollama_model


settings = Settings()

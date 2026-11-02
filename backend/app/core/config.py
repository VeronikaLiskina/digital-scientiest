from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.embedding_models import E5_MODEL_NAME
from app.services.reranker_service import DEFAULT_RERANKER_MODEL


class Settings(BaseSettings):
    database_url: str
    database_echo: bool = False
    upload_dir: str = "uploads"

    embedding_model_name: str = E5_MODEL_NAME
    embedding_batch_size: int = 16
    embedding_cpu_threads: int = 2
    embedding_max_concurrent_jobs: int = 1
    reranker_model_name: str = DEFAULT_RERANKER_MODEL
    reranker_batch_size: int = 4
    reranker_max_length: int = 768
    reranker_min_score: float = 0.5
    reranker_top_k: int = 6
    reranker_cpu_threads: int = 2
    reranker_max_concurrent_jobs: int = 1
    celery_broker_url: str = "redis://redis:6379/0"
    pdf_processing_max_retries: int = 3
    pdf_ocr_cache_enabled: bool = True

    llm_provider: Literal["groq", "api"] = "groq"
    llm_api_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_api_model: str = ""
    llm_api_timeout_seconds: int = 120
    llm_api_max_completion_tokens: int = 4096

    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: int = 120
    groq_max_completion_tokens: int = 4096
    groq_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    groq_max_retries: int = 1
    llm_local_fallback_enabled: bool = False
    llm_fallback_api_timeout_seconds: float = Field(default=30, gt=0)
    llm_fallback_cooldown_seconds: float = Field(default=60, ge=0)
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "gemma4:12b"
    ollama_timeout_seconds: int = Field(default=240, gt=0)
    ollama_keep_alive: str = "0"
    ollama_num_ctx: int = Field(default=16384, ge=2048)
    ollama_num_predict: int = Field(default=4096, ge=1)
    ollama_num_thread: int = Field(default=2, ge=1)
    ollama_num_batch: int = Field(default=128, ge=1)
    ollama_use_mmap: bool = True
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
        return self.llm_api_model if self.llm_provider == "api" else self.groq_model


settings = Settings()

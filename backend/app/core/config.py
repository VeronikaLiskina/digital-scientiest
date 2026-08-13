from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.embedding_models import E5_MODEL_NAME, LEGACY_MPNET_MODEL_NAME


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
    celery_broker_url: str = "redis://redis:6379/0"
    pdf_processing_max_retries: int = 3

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: int = 120
    ollama_keep_alive: str = "1m"
    ai_publication_analysis_enabled: bool = True
    ai_publication_analysis_mode: str = "fallback"
    ai_publication_analysis_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

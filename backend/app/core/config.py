from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    upload_dir: str = "uploads"

    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    embedding_dim: int = 768

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: int = 120
    ai_publication_analysis_enabled: bool = True
    ai_publication_analysis_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

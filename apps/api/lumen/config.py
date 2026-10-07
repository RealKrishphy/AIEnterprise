from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LUMEN_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://lumen:lumen@localhost:5432/lumen"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(min_length=32, default="development-only-secret-change-before-use")
    access_token_minutes: int = Field(default=15, gt=0, le=60)
    refresh_token_days: int = Field(default=30, gt=0, le=90)
    object_store_endpoint: str = "http://localhost:9000"
    object_store_bucket: str = "lumen-documents"
    object_store_access_key: str = "lumen"
    object_store_secret_key: str = "lumen-secret"
    object_store_region: str = "auto"
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = Field(default=64, gt=0, le=256)
    reranker_model: str = "BAAI/bge-reranker-base"
    retrieval_candidates: int = Field(default=50, gt=0, le=100)
    rerank_results: int = Field(default=8, gt=0, le=20)
    context_token_budget: int = Field(default=4000, gt=0, le=16000)
    clamav_host: str = "localhost"
    clamav_port: int = Field(default=3310, gt=0, le=65535)
    clamav_timeout_seconds: float = Field(default=10, gt=0, le=60)
    llm_model: str = "ollama/llama3.2"
    llm_api_base: str = "http://localhost:11434"
    llm_fallback_models: str = ""
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    query_rewrite_timeout_seconds: float = Field(default=2, gt=0, le=10)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    rate_limit_per_minute: int = Field(default=60, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()

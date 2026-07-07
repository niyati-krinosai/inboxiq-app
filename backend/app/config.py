from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Render/Railway provide postgres:// or postgresql:// — we need asyncpg."""
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "InboxIQ"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://inboxiq:inboxiq@localhost:5432/inboxiq"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def _validate_db_host(self) -> "Settings":
        host = urlparse(self.database_url).hostname
        if not host:
            raise ValueError("DATABASE_URL is missing a hostname — use the External Database URL from Render Postgres")
        return self

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Google OAuth — ONLY these scopes, never compose/send/delete
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/callback"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Token encryption at rest (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    token_encryption_key: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = ""  # e.g. https://openrouter.ai/api/v1 for OpenRouter keys
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Frontend (redirect target after OAuth)
    frontend_url: str = "http://localhost:3000"
    cors_extra_origins: str = ""  # comma-separated, e.g. https://inboxiq.vercel.app

    # Gmail — read-only scopes only
    gmail_scopes: list[str] = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    # Sync & processing
    initial_sync_max_messages: int = 2000
    sync_interval_seconds: int = 3600  # hourly background sync
    dedup_similarity_threshold: float = 0.85
    dedup_entity_boost: float = 0.10
    dedup_time_window_hours: int = 72
    pipeline_batch_size: int = 20
    celery_max_retries: int = 5
    celery_retry_backoff: int = 60

    # Source enrichment
    enrich_official_sources: bool = True
    enrich_max_urls_per_article: int = 3
    enrich_fetch_timeout_seconds: int = 15

    # Intelligence quality (Phase 16+)
    breaking_news_threshold: int = 5  # newsletters within window
    breaking_news_window_hours: int = 2
    trending_newsletter_threshold: int = 10
    company_weights: dict[str, float] = {
        "OpenAI": 1.0, "Anthropic": 0.95, "Google": 0.95, "Meta": 0.9,
        "Microsoft": 0.9, "Apple": 0.85, "Amazon": 0.85,
    }

    # Model versioning (Phase 8)
    extraction_model: str = "gpt-4o-mini"
    extraction_prompt_version: str = "v1"
    chat_model: str = "gpt-4o-mini"
    chat_prompt_version: str = "v1"
    canonicalize_prompt_version: str = "v1"

    # API rate limiting
    api_rate_limit_rpm: int = 120

    # Gmail Push Notifications (Phase 10)
    gmail_pubsub_topic: str = ""  # projects/PROJECT/topics/TOPIC
    gmail_webhook_secret: str = ""

    # Pipeline mode
    use_streaming_pipeline: bool = False  # event-driven per-stage workers when True
    simple_mode: bool = True  # lightweight: segment only, article-based chat (no LLM pipeline)

    def model_versions(self) -> dict:
        return {
            "extraction": {"model": self.extraction_model, "prompt_version": self.extraction_prompt_version},
            "embedding": {"model": self.embedding_model},
            "chat": {"model": self.chat_model, "prompt_version": self.chat_prompt_version},
            "canonicalize": {"model": self.openai_model, "prompt_version": self.canonicalize_prompt_version},
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

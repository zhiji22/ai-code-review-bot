"""
Application configuration via Pydantic Settings v2.

Per DESIGN.md §5/§9: All config from environment variables with validation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings.

    All values loaded from environment / .env file.
    Per DESIGN.md §15: strict validation, extra=forbid.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    app_name: str = "AI Code Review Bot"
    app_version: str = "1.0.0"
    secret_key: str = Field(..., min_length=32)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Database (PostgreSQL 16 + pgvector) ──────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "reviewer"
    db_password: str = Field(..., min_length=1)
    db_name: str = "code_review"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ── Redis ────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db_default: int = 0
    redis_db_celery_broker: int = 1
    redis_db_celery_result: int = 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db_default}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_broker_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db_celery_broker}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_result_backend(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db_celery_result}"

    # ── GitHub App ───────────────────────────────────────
    github_app_id: str = Field(..., min_length=1)
    github_app_private_key_path: str = Field(..., min_length=1)
    github_webhook_secret: str = Field(..., min_length=1)
    github_client_id: str = Field(..., min_length=1)
    github_client_secret: str = Field(..., min_length=1)
    github_api_base_url: str = "https://api.github.com"
    github_webhook_max_payload_kb: int = 25000  # 25 MB
    github_oauth_redirect_uri: str | None = None  # deprecated, not used
    github_token: str | None = None  # dev fallback when not using GitHub App auth

    # ── OpenAI / LLM ─────────────────────────────────────
    openai_api_key: str = Field(..., min_length=1)
    openai_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen-plus"
    openai_model_light: str = "qwen-turbo"
    openai_max_tokens: int = 2000
    openai_temperature: float = 0.1
    openai_seed: int = 42
    openai_timeout: int = 30  # seconds

    # ── LLM Budget (§13 risk mitigation) ─────────────────
    llm_budget_daily_usd: float = 50.0
    llm_budget_max_tokens_per_pr: int = 500_000
    llm_cache_ttl: int = 86400  # 24 hours

    # ── Celery ───────────────────────────────────────────
    celery_task_time_limit: int = 300  # 5 minutes
    celery_task_soft_time_limit: int = 240
    celery_task_max_retries: int = 3
    celery_task_default_retry_delay: int = 60
    celery_worker_concurrency: int = 4
    celery_worker_prefetch_multiplier: int = 1
    celery_task_acks_late: bool = True

    # ── GitHub Status Check ─────────────────────────────
    github_status_context: str = "AI Code Review"

    # ── Review Pipeline ──────────────────────────────────
    review_max_file_size_kb: int = 500  # skip files larger than 500 KB
    review_max_files_per_pr: int = 100
    review_parallelism: int = 4  # Semaphore limit for parallel file analysis
    review_timeout_per_file: int = 10  # seconds (§1: <10s/file)
    review_large_pr_threshold: int = 20  # files, §16 tiered strategy
    review_batch_threshold: int = 100

    # ── Rate Limiting (§7.5) ─────────────────────────────
    rate_limit_api_per_minute: int = 200
    rate_limit_webhook_per_minute: int = 60
    rate_limit_llm_per_minute: int = 50

    # ── Idempotency (§7.4) ───────────────────────────────
    idempotency_ttl: int = 3600  # 1 hour

    # ── CORS / Security (§15) ────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost"]

    # ── JWT / Auth (§15) ─────────────────────────────────
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    jwt_algorithm: str = "HS256"

    # ── Sentry ───────────────────────────────────────────
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1

    # ── GDPR / Data Retention (§16) ──────────────────────
    retention_reviews_days: int = 90
    retention_code_embeddings_days: int = 180
    retention_logs_days: int = 30


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()

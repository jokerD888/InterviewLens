"""Centralised settings loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    # ---- Database ----
    database_url: str = Field(
        default="postgresql+asyncpg://il:il_pass@localhost:5433/interviewlens"
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://il:il_pass@localhost:5433/interviewlens"
    )

    # ---- Redis / Celery ----
    redis_url: str = "redis://localhost:6380/0"
    cache_redis_url: str | None = None
    celery_broker_url: str = "redis://localhost:6380/1"
    celery_result_backend: str = "redis://localhost:6380/2"

    # ---- LLM ----
    deepseek_api_key: str = "sk-REPLACE_ME"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_chat: str = "deepseek-chat"
    deepseek_model_reasoner: str = "deepseek-reasoner"
    llm_concurrency: int = Field(default=4, ge=1, le=32)
    llm_requests_per_minute: int = Field(default=30, ge=1, le=1000)
    llm_daily_token_budget: int = Field(default=2_000_000, ge=1)
    admin_api_token: str = ""
    app_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3013",
        "http://127.0.0.1:3013",
    ]

    # ---- Embedding ----
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_dim: int = 1024
    inferpilot_server_url: str = "http://localhost:8000"

    # ---- Langfuse ----
    langfuse_host: str = "http://localhost:3001"
    langfuse_public_key: str = "pk-REPLACE_ME"
    langfuse_secret_key: str = "sk-REPLACE_ME"

    # ---- Nowcoder ----
    nowcoder_cookie: str = ""
    nowcoder_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # ---- Crawler ----
    crawler_rate_per_sec: float = 1.5
    crawler_jitter_min: float = 2.0
    crawler_jitter_max: float = 5.0
    crawler_max_retries: int = 3

    # ---- App ----
    app_env: str = "dev"
    public_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    search_requests_per_minute: int = Field(default=12, ge=1, le=1000)
    search_concurrency: int = Field(default=1, ge=1, le=4)
    search_timeout_seconds: float = Field(default=30, ge=1, le=120)
    trusted_search_proxy: str = ""
    log_level: str = "INFO"
    extract_prompt_version: int = 1
    answer_prompt_version: int = 1

    # ---- Search cache (read-path optimisation for /posts/search) ----
    search_cache_enabled: bool = True
    search_embed_ttl_seconds: int = 86_400  # 24h — embedding only depends on text + model
    search_result_ttl_seconds: int = 1_800  # 30min — full result depends on data too

    # ---- Bridge to daily-interview-prep ----
    daily_prep_api_url: str = "http://localhost:8000/api"
    daily_prep_token: str = ""

    @model_validator(mode="after")
    def production_safety(self):
        if self.app_env == "production":
            from urllib.parse import urlsplit

            if len(self.admin_api_token) < 32 or "REPLACE" in self.admin_api_token:
                raise ValueError("Production requires a strong administrator credential")
            for name in ("database_url", "redis_url", "cache_redis_url", "celery_broker_url", "celery_result_backend"):
                address = getattr(self, name)
                password = urlsplit(address or "").password or ""
                if len(password) < 32 or "REPLACE" in password:
                    raise ValueError(f"Production requires authenticated {name}")
            state, cache = urlsplit(self.redis_url), urlsplit(self.cache_redis_url or "")
            if (state.hostname, state.port or 6379) == (cache.hostname, cache.port or 6379):
                raise ValueError("Production cache and durable Redis must be separate instances")
            if any(not origin.startswith("https://") for origin in self.app_origins):
                raise ValueError("Production origins must use HTTPS")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

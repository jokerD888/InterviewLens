"""Centralised settings loaded from environment / .env via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
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
    celery_broker_url: str = "redis://localhost:6380/1"
    celery_result_backend: str = "redis://localhost:6380/2"

    # ---- LLM ----
    deepseek_api_key: str = "sk-REPLACE_ME"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_chat: str = "deepseek-chat"
    deepseek_model_reasoner: str = "deepseek-reasoner"

    # ---- Embedding ----
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_dim: int = 1024

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
    log_level: str = "INFO"
    extract_prompt_version: int = 1


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

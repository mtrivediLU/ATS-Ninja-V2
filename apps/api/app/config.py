from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

"""Centralized, environment-driven API settings.

All configuration flows through this one typed object (no scattered
``os.getenv`` calls, no hardcoded secrets). Later phases add database, Redis,
and auth settings here; each reads from the environment with an ``ATS_API_``
prefix so deployments configure the service without code changes.
"""


class Settings(BaseSettings):
    """Application settings, populated from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="ATS_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ATS-Ninja-V2 API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated in the environment, e.g. ATS_API_CORS_ORIGINS='["http://localhost:3000"]'
    cors_origins: list[str] = ["http://localhost:3000"]

    # Persistence (async SQLAlchemy). Default targets the local Compose Postgres;
    # override with ATS_API_DATABASE_URL. Tests use an in-memory SQLite engine.
    database_url: str = "postgresql+asyncpg://ats:ats@localhost:5432/ats_ninja"
    database_echo: bool = False

    # Async job queue broker (arq over Redis).
    redis_url: str = "redis://localhost:6379"

    # Bound the number of concurrent kit jobs a single worker will run.
    worker_max_jobs: int = 4

    # When True, the engine auto-detects a local LLM (Ollama) to raise quality;
    # it always falls back to the deterministic path. Tests set this False so
    # generation stays fully deterministic and offline.
    engine_use_llm: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()

"""
Application configuration.

Configuration is environment-driven (12-factor style) and segregated between
development and production via the APP_ENV variable, which selects the
.env file that is loaded:

    APP_ENV=development -> .env
    APP_ENV=production  -> .env.production

All values can still be overridden by real environment variables (env vars
always win over .env file contents), which is how production deployments
(containers, systemd units, CI) should supply secrets rather than committing
them to a file.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_file() -> str:
    app_env = os.getenv("APP_ENV", "development").lower()
    candidate = BASE_DIR / (".env.production" if app_env == "production" else ".env")
    return str(candidate) if candidate.exists() else ""


class Settings(BaseSettings):
    """Strongly typed application settings loaded from environment/.env."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "production"] = "development"

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "inventory_dev"
    db_user: str = "inventory_app"
    db_password: str = "change_me"
    db_sslmode: str = "prefer"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    # Logging
    log_level: str = "INFO"
    log_dir: str = "./logs"
    log_json: bool = False

    # Ingestion
    ingest_batch_size: int = 50_000
    ingest_file_extensions: str = ".xlsx,.xlsm"

    # Authentication
    remember_me_days: int = 30

    @computed_field  # type: ignore[misc]
    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?sslmode={self.db_sslmode}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[misc]
    @property
    def ingest_extensions_tuple(self) -> tuple[str, ...]:
        return tuple(
            ext.strip().lower() for ext in self.ingest_file_extensions.split(",") if ext.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Use get_settings.cache_clear() in tests."""
    return Settings()

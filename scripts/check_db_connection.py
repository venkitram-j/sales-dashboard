#!/usr/bin/env python3
"""Sanity-checks connectivity to the configured database.
Usage: APP_ENV=development python scripts/check_db_connection.py
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from app.config import get_settings


def main() -> int:
    settings = get_settings()
    print(f"APP_ENV={settings.app_env}")
    print(f"Connecting to {settings.db_host}:{settings.db_port}/{settings.db_name} as {settings.db_user} ...")
    try:
        engine = create_engine(settings.sqlalchemy_database_uri)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar()
        print(f"Connected OK. Server: {version}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Connection FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Runs data ingestion (parse + bulk-load new/modified Excel files from
app_settings.source_folder into sales_fact, then refresh mv_sales_fact)
without starting the Streamlit app.

Useful for scheduling independently of the UI -- e.g. a cron job or
systemd timer that keeps the dashboard's data fresh even if nobody has the
app open. Deliberately builds its own SQLAlchemy engine/session rather than
reusing app.database.get_engine()/session_scope() (which are
st.cache_resource-backed and meant for the Streamlit runtime).

Usage:
    APP_ENV=production python scripts/run_ingestion.py
Exit code is 0 if every discovered file ingested successfully (or was
already up to date), 1 if source_folder isn't configured yet or at least
one file failed to ingest.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.ingestion_service import IngestionService  # noqa: E402
from app.services.settings_service import SettingsService  # noqa: E402
from app.utils.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    settings = get_settings()
    logger.info("Starting standalone ingestion run (APP_ENV=%s)", settings.app_env)

    engine = create_engine(settings.sqlalchemy_database_uri, pool_pre_ping=True, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()

    try:
        settings_service = SettingsService(session)
        settings_service.bootstrap_defaults()
        session.commit()

        if not settings_service.is_configured():
            print(
                "source_folder has not been configured yet -- run the app once and "
                "complete initial setup before scheduling standalone ingestion.",
                file=sys.stderr,
            )
            return 1

        app_settings = settings_service.get_all()
        ingestion_service = IngestionService(session, engine)
        result = ingestion_service.ingest_all(
            source_folder=app_settings["source_folder"],
            header_row=app_settings["header_row"],
            start_col=app_settings["start_col"],
            extensions=settings.ingest_extensions_tuple,
        )
    finally:
        session.close()
        engine.dispose()

    print(
        f"Ingested: {len(result.ingested_files)} new, "
        f"{len(result.reingested_files)} re-ingested, "
        f"{len(result.skipped_unchanged)} unchanged, "
        f"{len(result.failed_files)} failed, "
        f"{result.total_rows_inserted} row(s) inserted."
    )

    if result.failed_files:
        print("Failed files:", file=sys.stderr)
        for name, err in result.failed_files.items():
            print(f"  - {name}: {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

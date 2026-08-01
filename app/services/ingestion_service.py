"""Ingestion service.

Scans app_settings.source_folder for Excel files, decides which are new or
modified since their last ingestion (tracked via ingested_files), and bulk
loads them into sales_fact using PostgreSQL's COPY protocol -- the fastest
way to load millions of rows (far faster than row-by-row INSERT or even
executemany/to_sql).

Ordering note: sales_fact.source_file has a foreign key to
ingested_files.file_name. The bulk COPY runs on its own raw DB connection/
transaction (see _bulk_copy), separate from the SQLAlchemy ORM session used
for everything else here -- so the ingested_files row for a new file must
be committed *before* COPY-ing that file's rows into sales_fact, or the
COPY fails with a ForeignKeyViolation (the row it references doesn't exist
yet from the COPY connection's point of view). ingest_file() below commits
the ingested_files upsert first, then COPYs; if the COPY then fails for any
reason, the ingested_files row is deleted again so a failed ingest never
leaves an orphaned record with no matching sales_fact rows.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.ingested_file import IngestedFile
from app.models.sales_fact import SalesFact
from app.services.file_parser_service import SourceFileParseError, parse_sales_excel
from app.services.materialized_view_service import refresh_sales_fact_view
from app.utils.filename_parser import FileNamePeriodError, parse_period_from_filename

logger = logging.getLogger(__name__)

SALES_FACT_COLUMNS = [
    "product_code",
    "description",
    "branch",
    "sales_qty",
    "pending_po",
    "admin",
    "buyer",
    "source_file",
    "period_start",
    "period_end",
]


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Normalizes a datetime to timezone-aware UTC. Some DB drivers/configs
    can round-trip a DateTime(timezone=True) column back as naive; treat a
    naive value as already being UTC rather than letting the comparison in
    ingest_all() raise TypeError."""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


@dataclass
class IngestionResult:
    ingested_files: list[str] = field(default_factory=list)
    skipped_unchanged: list[str] = field(default_factory=list)
    reingested_files: list[str] = field(default_factory=list)
    failed_files: dict[str, str] = field(default_factory=dict)
    total_rows_inserted: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.ingested_files or self.reingested_files)


class IngestionService:
    def __init__(self, session: Session, engine: Engine):
        self.session = session
        self.engine = engine

    # -- discovery -----------------------------------------------------
    def scan_source_folder(self, source_folder: str, extensions: tuple[str, ...]) -> list[Path]:
        folder = Path(source_folder)
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"source_folder '{source_folder}' does not exist or is not a directory")
        files = [
            p
            for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in extensions and not p.name.startswith("~$")
        ]
        return files

    def _existing_record(self, file_name: str) -> IngestedFile | None:
        return self.session.scalar(select(IngestedFile).where(IngestedFile.file_name == file_name))

    # -- bulk load -------------------------------------------------------
    def _bulk_copy(self, df: pd.DataFrame) -> int:
        """Bulk-load df into sales_fact via PostgreSQL COPY, on its own raw
        connection/transaction (see module docstring for why ordering
        around this call matters). Returns row count."""
        if df.empty:
            return 0
        raw_conn = self.engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            columns_sql = ", ".join(SALES_FACT_COLUMNS)
            copy_sql = f"COPY sales_fact ({columns_sql}) FROM STDIN"
            records = df[SALES_FACT_COLUMNS].itertuples(index=False, name=None)
            with cursor.copy(copy_sql) as copy:  # psycopg3 copy API
                for row in records:
                    copy.write_row(row)
            raw_conn.commit()
            return len(df)
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()

    def _delete_rows_for_file(self, file_name: str) -> None:
        self.session.execute(delete(SalesFact).where(SalesFact.source_file == file_name))

    def _upsert_ingested_file_record(self, file_path: Path, row_count: int) -> IngestedFile:
        stat = file_path.stat()
        record = self._existing_record(file_path.name)
        if record is None:
            record = IngestedFile(file_name=file_path.name)
            self.session.add(record)
        record.file_path = str(file_path)
        record.file_mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
        record.file_size_bytes = stat.st_size
        record.row_count = row_count
        self.session.flush()
        return record

    def _delete_ingested_file_record(self, file_name: str) -> None:
        self.session.execute(delete(IngestedFile).where(IngestedFile.file_name == file_name))
        self.session.commit()

    # -- single file -------------------------------------------------------
    def ingest_file(
        self,
        file_path: Path,
        header_row: int,
        start_col: str,
        is_reingest: bool,
    ) -> int:
        """Parse + load one file. Returns rows inserted. Raises on failure;
        any ingested_files row created for this file is removed again
        before the exception propagates, so a failed ingest never leaves an
        orphaned record."""
        period = parse_period_from_filename(file_path.name)
        df = parse_sales_excel(file_path, header_row=header_row, start_col=start_col)
        df["source_file"] = file_path.name
        df["period_start"] = period.period_start
        df["period_end"] = period.period_end

        if is_reingest:
            self._delete_rows_for_file(file_path.name)

        # Commit the ingested_files row (and the delete-old-rows above, if
        # any) now, before the bulk COPY -- see module docstring.
        self._upsert_ingested_file_record(file_path, row_count=len(df))
        self.session.commit()

        try:
            row_count = self._bulk_copy(df)
        except Exception:
            logger.exception("Bulk load failed for %s; removing its ingested_files record", file_path.name)
            self._delete_ingested_file_record(file_path.name)
            raise

        return row_count

    # -- orchestration -------------------------------------------------------
    def ingest_all(
        self,
        source_folder: str,
        header_row: int,
        start_col: str,
        extensions: tuple[str, ...] = (".xlsx", ".xlsm"),
        refresh_view: bool = True,
    ) -> IngestionResult:
        result = IngestionResult()
        files = self.scan_source_folder(source_folder, extensions)

        for file_path in files:
            stat = file_path.stat()
            mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
            existing = self._existing_record(file_path.name)

            is_new = existing is None
            is_modified = existing is not None and _as_utc(existing.file_mtime) < mtime
            if not is_new and not is_modified:
                result.skipped_unchanged.append(file_path.name)
                continue

            try:
                rows = self.ingest_file(
                    file_path, header_row=header_row, start_col=start_col, is_reingest=is_modified
                )
                result.total_rows_inserted += rows
                if is_modified:
                    result.reingested_files.append(file_path.name)
                else:
                    result.ingested_files.append(file_path.name)
            except (SourceFileParseError, FileNamePeriodError) as exc:
                logger.error("Failed to ingest %s: %s", file_path.name, exc)
                result.failed_files[file_path.name] = str(exc)
            except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the batch
                logger.exception("Unexpected error ingesting %s", file_path.name)
                result.failed_files[file_path.name] = str(exc)

        if refresh_view and result.has_changes:
            refresh_sales_fact_view(self.session)

        logger.info(
            "Ingestion complete: %d new, %d reingested, %d unchanged, %d failed, %d rows inserted",
            len(result.ingested_files),
            len(result.reingested_files),
            len(result.skipped_unchanged),
            len(result.failed_files),
            result.total_rows_inserted,
        )
        return result

    def reset_all_sales_data(self) -> None:
        """Wipes sales_fact and ingested_files entirely (used when
        source_folder changes, before a full re-ingest)."""
        self.session.execute(delete(SalesFact))
        self.session.execute(delete(IngestedFile))
        self.session.flush()
        logger.warning("All sales_fact and ingested_files data has been reset")

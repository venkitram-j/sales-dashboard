"""Ingestion service.

Scans app_settings.source_folder for Excel files, decides which are new or
modified since their last ingestion (tracked via ingested_files), and bulk
loads them into sales_fact using PostgreSQL's COPY protocol -- the fastest
way to load millions of rows (far faster than row-by-row INSERT or even
executemany/to_sql).
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
        """Bulk-load df into sales_fact via PostgreSQL COPY. Returns row count."""
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
        self.session.flush()

    # -- single file -------------------------------------------------------
    def ingest_file(
        self,
        file_path: Path,
        header_row: int,
        start_col: str,
        is_reingest: bool,
    ) -> int:
        """Parse + load one file. Returns rows inserted. Raises on failure
        (caller decides how to record the failure)."""
        period = parse_period_from_filename(file_path.name)
        df = parse_sales_excel(file_path, header_row=header_row, start_col=start_col)
        df["source_file"] = file_path.name
        df["period_start"] = period.period_start
        df["period_end"] = period.period_end

        if is_reingest:
            self._delete_rows_for_file(file_path.name)

        row_count = self._bulk_copy(df)

        stat = file_path.stat()
        record = self._existing_record(file_path.name)
        if record is None:
            record = IngestedFile(file_name=file_path.name)
            self.session.add(record)
        record.file_path = str(file_path)
        record.file_mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
        record.file_size_bytes = stat.st_size
        record.period_start = period.period_start
        record.period_end = period.period_end
        record.row_count = row_count
        record.status = "success"
        record.error_message = None
        self.session.flush()
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
            is_modified = existing is not None and existing.file_mtime < mtime
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
                record = self._existing_record(file_path.name) or IngestedFile(file_name=file_path.name)
                record.file_path = str(file_path)
                record.file_mtime = mtime
                record.file_size_bytes = stat.st_size
                record.status = "failed"
                record.error_message = str(exc)
                record.row_count = record.row_count or 0
                record.period_start = record.period_start or dt.date.today()
                record.period_end = record.period_end or dt.date.today()
                self.session.add(record)
                self.session.flush()

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

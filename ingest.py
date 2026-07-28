"""
Ingest new or modified Excel files into Postgres.

Run manually:
    python ingest.py

Where to look and how to parse files (source folder, header row, start
column, columns to read) is configured in the DATABASE, via the
dashboard's Settings panel — not in .env. This script reads that config
at the start of each run, so changes made in the dashboard take effect
on the next run without redeploying. If no source folder has been
configured yet, this exits early with a message telling you to set one.

In production this is scheduled (cron / Task Scheduler) to run daily
after new files land in the folder. It is idempotent and safe to re-run:
already-ingested, unchanged files are skipped; a changed file has its old
rows replaced.
"""

import glob
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2.extras
from openpyxl.utils import column_index_from_string

from db import get_conn, get_settings, init_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ingest")

# Specify column names from Excel file
COLUMNS_TO_READ = ["Product Code", "Description", "Branch", "Sales Qty", "Pending PO", "Admin", "Buyer"]

# Specify the database columns here according to data type
STRING_COLS = ["product_code", "description", "branch", "admin", "buyer"]
NUMERIC_COLS = ["sales_qty", "pending_po"]

MTIME_TOLERANCE_SECONDS = 1.0  # avoid re-processing due to float rounding

# ---------------------------------------------------------------------------
# Period parsing from file names.
#
# Since these files hold a year or six months of data with no per-row date
# column, the period each file covers is declared in its FILE NAME using
# one of these patterns (checked in this order):
#
#   ..._2024-01-01_to_2024-06-30...   -> explicit custom range
#   ..._2024H1... / ..._2024-H2...    -> first/second half of that year
#   ..._2024...                       -> a bare 4-digit year -> full year
#
# Branch name, extension, etc. can appear anywhere else in the name, e.g.:
#   NorthBranch_2024H1.xlsx
#   South_Store_2024-07-01_to_2024-12-31.xlsx
#   Warehouse3_2023.xlsx
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})_to_(\d{4})-(\d{2})-(\d{2})")
_HALF_RE = re.compile(r"(\d{4})[-_]?H([12])", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def parse_period_from_filename(file_name):
    """Return (period_start, period_end) as date objects, or (None, None)
    if the file name doesn't match any known pattern."""
    stem = Path(file_name).stem

    m = _RANGE_RE.search(stem)
    if m:
        y1, mo1, d1, y2, mo2, d2 = map(int, m.groups())
        return date(y1, mo1, d1), date(y2, mo2, d2)

    m = _HALF_RE.search(stem)
    if m:
        year, half = int(m.group(1)), int(m.group(2))
        if half == 1:
            return date(year, 1, 1), date(year, 6, 30)
        return date(year, 7, 1), date(year, 12, 31)

    m = _YEAR_RE.search(stem)
    if m:
        year = int(m.group(1))
        return date(year, 1, 1), date(year, 12, 31)

    return None, None


def list_source_files(source_folder):
    paths = sorted(
        glob.glob(os.path.join(source_folder, "*.xlsx"))
        + glob.glob(os.path.join(source_folder, "*.xls"))
    )
    return {Path(p).name: (p, os.path.getmtime(p)) for p in paths}


def get_ingested_mtimes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT file_name, file_mtime FROM ingested_files")
        return dict(cur.fetchall())


def read_excel_file(path, header_row, start_col):
    """Read one file per the configured header row / start column /
    column subset (all sourced from the database settings). Raises on
    missing expected columns."""
    df = pd.read_excel(path, header=header_row - 1)

    # Drop columns before start_col by position (rather than using
    # usecols="B:XFD", which pandas rejects as out-of-bounds on sheets
    # narrower than column XFD — i.e. basically all real files).
    start_idx = column_index_from_string(start_col) - 1
    if start_idx > 0:
        df = df.iloc[:, start_idx:]

    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")

    unnamed = [c for c in df.columns if str(c).startswith("Unnamed")]
    for c in unnamed:
        if df[c].isna().all():
            df = df.drop(columns=c)

    if COLUMNS_TO_READ:
        missing = [c for c in COLUMNS_TO_READ if c not in df.columns]
        if missing:
            raise ValueError(f"missing expected column(s): {', '.join(missing)}")
        df = df[COLUMNS_TO_READ]

    return df


def normalize_col(name):
    """lowercase, spaces -> underscores — applied to the columns pulled
    via COLUMNS_TO_READ"""
    return str(name).strip().lower().replace(" ", "_")

def denormalize_col(name):
    """title case, underscores -> spaces — applied to the columns pulled
    from the dataframe for appropriate display"""
    return str(name).replace("_", " ").title()


def build_fact_rows(df, file_name, period_start, period_end):
    """Normalize a raw file's dataframe into the sales_fact row shape.

    The columns selected via COLUMNS_TO_READ are renamed here to
    lowercase-with-underscores (e.g. "Sale Amount" -> "sale_amount")
    before use, and the *_COL config values are normalized the same way
    so the lookup still matches regardless of case/spacing differences
    between the .env mapping and the actual Excel header text.
    """
    df = df.rename(columns={c: normalize_col(c) for c in df.columns})

    out = pd.DataFrame()

    for col in STRING_COLS:
        out[col] = df[col].astype(str).str.strip()

    for col in NUMERIC_COLS:
        out[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Every row gets the file's overall period, regardless of whether it
    # also has a per-row sale_date — this is what lets date-range filters
    # work even for files with no per-row dates.
    out["period_start"] = period_start
    out["period_end"] = period_end
    out["source_file"] = file_name
    return out.dropna()


def replace_file_rows(conn, file_name, file_mtime, period_start, period_end, rows_df, status="ok", error_message=None):
    """Delete any existing rows for this file, insert the new rows, and
    record the file's ingestion status — all in the caller's transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingested_files (file_name, file_mtime, row_count, period_start, period_end, ingested_at, status, error_message)
            VALUES (%s, %s, %s, %s, %s, now(), %s, %s)
            ON CONFLICT (file_name) DO UPDATE SET
                file_mtime = EXCLUDED.file_mtime,
                row_count = EXCLUDED.row_count,
                period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                ingested_at = EXCLUDED.ingested_at,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message
            """,
            (file_name, file_mtime, len(rows_df), period_start, period_end, status, error_message),
        )
        cur.execute("DELETE FROM sales_fact WHERE source_file = %s", (file_name,))
        if not rows_df.empty:
            records = list(
                rows_df[["product_code", "branch", "description", "period_start", "period_end", "sales_qty", "pending_po", "admin", "buyer", "source_file"]]
                .itertuples(index=False, name=None)
            )
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO sales_fact (product_code, branch, description, period_start, period_end, sales_qty, pending_po, admin, buyer, source_file)
                VALUES %s
                """,
                records,
                page_size=5000,
            )


def run_ingestion():
    init_schema()

    settings = get_settings()
    source_folder = settings["source_folder"]
    header_row = settings["header_row"]
    start_col = settings["start_col"]

    if not source_folder:
        log.error(
            "No SOURCE_FOLDER configured. Set it in the dashboard's Settings panel and try again."
        )
        sys.exit(1)

    if not os.path.isdir(source_folder):
        log.error("Configured SOURCE_FOLDER does not exist or isn't accessible: %s", source_folder)
        sys.exit(1)

    files = list_source_files(source_folder)
    if not files:
        log.info("No Excel files found in %s", source_folder)
        return

    with get_conn() as conn:
        conn.autocommit = False
        ingested = get_ingested_mtimes(conn)

        to_process = [
            name for name, (_, mtime) in files.items()
            if name not in ingested or mtime > ingested[name] + MTIME_TOLERANCE_SECONDS
        ]

        if not to_process:
            log.info("Up to date: %d file(s), nothing new to ingest.", len(files))
            return

        log.info("Ingesting %d new/modified file(s): %s", len(to_process), ", ".join(to_process))

        ok_count, err_count = 0, 0
        for name in to_process:
            path, mtime = files[name]
            period_start, period_end = parse_period_from_filename(name)
            if period_start is None:
                log.warning(
                    "  %s: no period pattern matched in the file name and no DATE_COL is "
                    "configured — this file's rows won't be filterable by date range. "
                    "Rename it to include e.g. '_2024H1' or '_2024'.",
                    name,
                )
            try:
                df = read_excel_file(path, header_row, start_col)
                rows = build_fact_rows(df, name, period_start, period_end)
                replace_file_rows(conn, name, mtime, period_start, period_end, rows, status="ok")
                conn.commit()
                ok_count += 1
                period_note = f" [{period_start} to {period_end}]" if period_start else ""
                log.info("OK   %-40s %d row(s)%s", name, len(rows), period_note)
            except Exception as e:
                conn.rollback()
                err_count += 1
                log.exception("FAIL %s (%s)", name, e)
                try:
                    replace_file_rows(
                        conn, name, mtime, period_start, period_end,
                        pd.DataFrame(), status="error", error_message=str(e),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    log.exception("Could not even record failure status for %s", name)

    log.info("Ingestion complete: %d succeeded, %d failed.", ok_count, err_count)

"""Parses a single source Excel file into a normalized DataFrame ready for
bulk-loading into sales_fact.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from openpyxl.utils import column_index_from_string

from app.utils.column_normalization import normalize_column_name

logger = logging.getLogger(__name__)

# Excel column headers (source) -> normalized DB field names (target).
# Keep this in sync with SalesFact's columns.
REQUIRED_TARGET_COLUMNS = {
    "product_code",
    "description",
    "branch",
    "sales_qty",
    "pending_po",
    "admin",
    "buyer",
}


class SourceFileParseError(ValueError):
    """Raised when a source Excel file can't be parsed as expected."""


def parse_sales_excel(file_path: Path, header_row: int, start_col: str) -> pd.DataFrame:
    """Read one Excel file into a DataFrame with normalized column names.

    header_row: 1-based row number containing the column headers.
    start_col: Excel column letter (e.g. 'A') where data begins; columns to
        the left of it are ignored.
    """
    start_idx = column_index_from_string(start_col) - 1  # 0-based

    try:
        raw = pd.read_excel(
            file_path,
            header=header_row - 1,
            engine="openpyxl",
        )
    except Exception as exc:  # noqa: BLE001 - surface as a domain error
        raise SourceFileParseError(f"Failed to read Excel file '{file_path.name}': {exc}") from exc

    raw = raw.iloc[:, start_idx:]
    raw.columns = [normalize_column_name(c) for c in raw.columns]

    missing = REQUIRED_TARGET_COLUMNS - set(raw.columns)
    if missing:
        raise SourceFileParseError(
            f"File '{file_path.name}' is missing required column(s): {sorted(missing)}. "
            f"Found columns: {list(raw.columns)}. Ensure the header row is at row "
            f"{header_row} and data starts at column {start_col}."
        )

    df = raw[list(REQUIRED_TARGET_COLUMNS)].copy()

    # Drop fully-empty rows (common trailing blank rows in Excel exports).
    df = df.dropna(how="all")
    df = df[df["product_code"].notna()]

    df["product_code"] = df["product_code"].astype(str).str.strip()
    df["branch"] = df["branch"].astype(str).str.strip()
    df["description"] = df["description"].astype(str).str.strip()
    df["admin"] = df["admin"].astype(str).str.strip()
    df["buyer"] = df["buyer"].astype(str).str.strip()
    df["sales_qty"] = pd.to_numeric(df["sales_qty"], errors="coerce")
    df["pending_po"] = pd.to_numeric(df["pending_po"], errors="coerce")

    logger.info("Parsed %s rows from %s", len(df), file_path.name)
    return df

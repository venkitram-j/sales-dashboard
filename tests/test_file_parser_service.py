from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from app.services.file_parser_service import SourceFileParseError, parse_sales_excel


def _write_workbook(path: Path, header_row: int, start_col_offset: int) -> None:
    """Writes a small workbook with `start_col_offset` blank columns before
    the real data, and `header_row - 1` blank rows before the header."""
    wb = openpyxl.Workbook()
    ws = wb.active

    headers = ["Product Code", "Description", "Branch", "Sales Qty", "Pending PO", "Admin", "Buyer"]
    row_data = [
        ["P001", "Widget", "B1", 10, 2, "Alice", "Bob"],
        ["P002", "Gadget", "B2", 5, 0, "Alice", "Carol"],
    ]

    for r in range(1, header_row):
        ws.cell(row=r, column=1, value="junk")

    for c, header in enumerate(headers, start=1 + start_col_offset):
        ws.cell(row=header_row, column=c, value=header)

    for i, row in enumerate(row_data):
        for c, value in enumerate(row, start=1 + start_col_offset):
            ws.cell(row=header_row + 1 + i, column=c, value=value)

    wb.save(path)


def test_parses_with_header_row_and_start_col(tmp_path: Path):
    file_path = tmp_path / "Sales_20260101_20260131.xlsx"
    _write_workbook(file_path, header_row=3, start_col_offset=2)  # data starts at col C

    df = parse_sales_excel(file_path, header_row=3, start_col="C")

    assert len(df) == 2
    assert set(df["product_code"]) == {"P001", "P002"}
    assert df.loc[df["product_code"] == "P001", "sales_qty"].iloc[0] == 10


def test_raises_on_missing_required_columns(tmp_path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Product Code", "Description"])
    ws.append(["P001", "Widget"])
    file_path = tmp_path / "Sales_20260101_20260131.xlsx"
    wb.save(file_path)

    with pytest.raises(SourceFileParseError):
        parse_sales_excel(file_path, header_row=1, start_col="A")

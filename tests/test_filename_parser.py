from __future__ import annotations

import datetime as dt

import pytest

from app.utils.filename_parser import FileNamePeriodError, parse_period_from_filename


def test_parses_compact_dates():
    result = parse_period_from_filename("Sales_20260101_20260131.xlsx")
    assert result.period_start == dt.date(2026, 1, 1)
    assert result.period_end == dt.date(2026, 1, 31)


def test_parses_dashed_dates():
    result = parse_period_from_filename("Branch12-Sales_2026-01-01_2026-01-31.xlsx")
    assert result.period_start == dt.date(2026, 1, 1)
    assert result.period_end == dt.date(2026, 1, 31)


def test_allows_trailing_suffix():
    result = parse_period_from_filename("Sales_20260201_20260228_v2.xlsx")
    assert result.period_start == dt.date(2026, 2, 1)
    assert result.period_end == dt.date(2026, 2, 28)


def test_rejects_missing_dates():
    with pytest.raises(FileNamePeriodError):
        parse_period_from_filename("no_dates_here.xlsx")


def test_rejects_reversed_dates():
    with pytest.raises(FileNamePeriodError):
        parse_period_from_filename("Sales_20260131_20260101.xlsx")

"""Parses period_start / period_end out of a source Excel file name.

Required naming convention (documented in the README as well):

    <anything>_YYYYMMDD_YYYYMMDD.xlsx
    <anything>_YYYY-MM-DD_YYYY-MM-DD.xlsx

Examples of valid file names:
    Sales_20260101_20260131.xlsx
    Branch12-Sales_2026-01-01_2026-01-31.xlsx
    Sales_20260201_20260228_v2.xlsx   (trailing suffix after the 2nd date is fine)

The two dates are taken to be the period_start and period_end for every row
ingested from that file. Both dates are required; a file whose name doesn't
contain a matching pair of dates is rejected with a descriptive error so the
person doing the ingestion can rename it correctly.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_DATE_COMPACT = r"(\d{4})(\d{2})(\d{2})"
_DATE_DASHED = r"(\d{4})-(\d{2})-(\d{2})"

_PATTERN = re.compile(
    rf"(?:{_DATE_COMPACT}|{_DATE_DASHED})[_\-](?:{_DATE_COMPACT}|{_DATE_DASHED})"
)


class FileNamePeriodError(ValueError):
    """Raised when a file name doesn't contain a parseable period."""


@dataclass(frozen=True)
class ParsedPeriod:
    period_start: dt.date
    period_end: dt.date


def _groups_to_date(groups: tuple[str | None, ...]) -> dt.date:
    year, month, day = (int(g) for g in groups if g is not None)
    return dt.date(year, month, day)


def parse_period_from_filename(file_name: str) -> ParsedPeriod:
    """Extract (period_start, period_end) from a file name.

    Raises FileNamePeriodError with actionable guidance if the name doesn't
    match the required convention or the end date precedes the start date.
    """
    match = _PATTERN.search(file_name)
    if not match:
        raise FileNamePeriodError(
            f"Could not find a start/end date pair in file name '{file_name}'. "
            "Expected the file to contain two dates like "
            "'..._20260101_20260131.xlsx' or '..._2026-01-01_2026-01-31.xlsx' "
            "(period_start followed by period_end)."
        )

    groups = match.groups()
    # groups layout: (compact_y,m,d, dashed_y,m,d) repeated twice -> 12 groups
    first = groups[0:6]
    second = groups[6:12]
    start_date = _groups_to_date(first)
    end_date = _groups_to_date(second)

    if end_date < start_date:
        raise FileNamePeriodError(
            f"In file name '{file_name}', the second date ({end_date}) is "
            f"earlier than the first date ({start_date}). The file name must "
            "list period_start before period_end."
        )

    return ParsedPeriod(period_start=start_date, period_end=end_date)

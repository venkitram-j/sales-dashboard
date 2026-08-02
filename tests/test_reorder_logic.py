from __future__ import annotations

import datetime as dt

import pytest

from app.services.reorder_logic import classify_priority, classify_reorder_status

TODAY = dt.date(2026, 8, 1)


@pytest.mark.parametrize(
    "avg_daily_sales,expected",
    [
        (0, "LOW"),
        (499, "LOW"),
        (499.99, "LOW"),
        (500, "MEDIUM"),
        (500.01, "MEDIUM"),
        (999, "MEDIUM"),
        (999.99, "MEDIUM"),
        (1000, "HIGH"),
        (1000.01, "HIGH"),
        (50000, "HIGH"),
    ],
)
def test_classify_priority_thresholds(avg_daily_sales, expected):
    assert classify_priority(avg_daily_sales) == expected


@pytest.mark.parametrize(
    "days_from_today,priority,expected",
    [
        # reorder_date <= today -> OVERDUE/REORDER/PLAN by priority
        (-5, "HIGH", "OVERDUE"),
        (0, "HIGH", "OVERDUE"),
        (-5, "MEDIUM", "REORDER"),
        (0, "MEDIUM", "REORDER"),
        (-5, "LOW", "PLAN"),
        (0, "LOW", "PLAN"),
        # today < reorder_date <= today+2 -> REORDER/PLAN/OK
        (1, "HIGH", "REORDER"),
        (2, "HIGH", "REORDER"),
        (1, "MEDIUM", "PLAN"),
        (2, "MEDIUM", "PLAN"),
        (1, "LOW", "OK"),
        (2, "LOW", "OK"),
        # today+2 < reorder_date <= today+4 -> PLAN (HIGH only) / OK
        (3, "HIGH", "PLAN"),
        (4, "HIGH", "PLAN"),
        (3, "MEDIUM", "OK"),
        (4, "MEDIUM", "OK"),
        (3, "LOW", "OK"),
        (4, "LOW", "OK"),
        # reorder_date > today+4 -> OK regardless of priority
        (5, "HIGH", "OK"),
        (5, "MEDIUM", "OK"),
        (5, "LOW", "OK"),
        (100, "HIGH", "OK"),
    ],
)
def test_classify_reorder_status_ladder(days_from_today, priority, expected):
    reorder_date = TODAY + dt.timedelta(days=days_from_today)
    assert classify_reorder_status(reorder_date, priority, today=TODAY) == expected


def test_classify_reorder_status_defaults_today_to_date_today(monkeypatch):
    class _FixedDate(dt.date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr(dt, "date", _FixedDate)
    assert classify_reorder_status(TODAY, "HIGH") == "OVERDUE"

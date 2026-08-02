"""Priority and reorder-status classification rules.

These thresholds are baked directly into mv_sales_fact's SQL (see
alembic/versions/0004_..._mv_sales_fact_reorder_columns.py) because the
materialized view needs to compute them per row without a round-trip to
Python. This module exists so the *exact same rules* are expressed once,
in plain testable Python, as a reference: if you change a threshold, change
it in both places (the SQL CASE expressions are commented with a pointer
back here).
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

Priority = Literal["HIGH", "MEDIUM", "LOW"]
ReorderStatus = Literal["OVERDUE", "REORDER", "PLAN", "OK"]

HIGH_PRIORITY_THRESHOLD = 1000
MEDIUM_PRIORITY_THRESHOLD = 500


def classify_priority(average_daily_sales: float) -> Priority:
    """HIGH if >= 1000/day, MEDIUM if >= 500/day, else LOW."""
    if average_daily_sales >= HIGH_PRIORITY_THRESHOLD:
        return "HIGH"
    if average_daily_sales >= MEDIUM_PRIORITY_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def classify_reorder_status(
    reorder_date: dt.date, priority: Priority, today: dt.date | None = None
) -> ReorderStatus:
    """Escalating urgency ladder, severity tiered by priority:

    - reorder_date <= today       -> OVERDUE (HIGH) / REORDER (MEDIUM) / PLAN (LOW)
    - reorder_date <= today + 2d  -> REORDER (HIGH) / PLAN (MEDIUM)    / OK (LOW)
    - reorder_date <= today + 4d  -> PLAN (HIGH)    / OK (MEDIUM, LOW)
    - otherwise                   -> OK
    """
    today = today or dt.date.today()

    if reorder_date <= today:
        if priority == "HIGH":
            return "OVERDUE"
        if priority == "MEDIUM":
            return "REORDER"
        return "PLAN"

    if reorder_date <= today + dt.timedelta(days=2):
        if priority == "HIGH":
            return "REORDER"
        if priority == "MEDIUM":
            return "PLAN"
        return "OK"

    if reorder_date <= today + dt.timedelta(days=4):
        return "PLAN" if priority == "HIGH" else "OK"

    return "OK"

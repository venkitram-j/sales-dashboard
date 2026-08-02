from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

TimeRange = Literal["ALL", "LAST_7_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"]

# Maps the UI's labels to mv_sales_fact's `time_range` bucket values (see
# alembic/versions/0004_..._mv_sales_fact_reorder_columns.py).
TIME_RANGE_OPTIONS: dict[str, TimeRange] = {
    "All": "ALL",
    "Last 7 Days": "LAST_7_DAYS",
    "Last 30 Days": "LAST_30_DAYS",
    "Last 90 Days": "LAST_90_DAYS",
}


@dataclass
class DashboardFilters:
    time_range: TimeRange = "ALL"
    product_codes: list[str] | None = None
    branches: list[str] | None = None
    departments: list[str] | None = None
    search_text: str | None = None
    limit: int = 5000


class DashboardService:
    """Reads from mv_sales_fact only -- never sales_fact directly -- so
    dashboard queries stay fast regardless of how large the base table gets.

    mv_sales_fact holds up to one row per sales_fact row per time_range
    bucket it falls into (see the migration referenced above), carrying
    per-branch/product_code aggregate columns (total_sales_qty, priority,
    reorder_date, etc. -- identical across every row in the same
    (time_range, branch, product_code) group, computed via window
    functions). Queries here use `DISTINCT ON (branch, product_code)` to
    collapse that back down to one summary row per branch/product for
    display, picking the most recently reported row as the representative
    one when there are several (e.g. multiple files ingested for the same
    branch/product within the selected window).
    """

    def __init__(self, session: Session):
        self.session = session

    def get_distinct_product_codes(self, time_range: TimeRange = "ALL") -> list[str]:
        rows = self.session.execute(
            text(
                "SELECT DISTINCT product_code FROM mv_sales_fact "
                "WHERE time_range = :time_range ORDER BY product_code LIMIT 5000"
            ),
            {"time_range": time_range},
        )
        return [r[0] for r in rows]

    def get_distinct_branches(self, time_range: TimeRange = "ALL") -> list[str]:
        rows = self.session.execute(
            text(
                "SELECT DISTINCT branch FROM mv_sales_fact "
                "WHERE time_range = :time_range ORDER BY branch LIMIT 5000"
            ),
            {"time_range": time_range},
        )
        return [r[0] for r in rows]

    def get_distinct_departments(self, time_range: TimeRange = "ALL") -> list[str]:
        rows = self.session.execute(
            text(
                "SELECT DISTINCT department FROM mv_sales_fact "
                "WHERE time_range = :time_range ORDER BY department LIMIT 5000"
            ),
            {"time_range": time_range},
        )
        return [r[0] for r in rows]

    def query(self, filters: DashboardFilters) -> pd.DataFrame:
        clauses: list[str] = ["time_range = :time_range"]
        params: dict[str, object] = {"time_range": filters.time_range, "limit": filters.limit}

        if filters.product_codes:
            clauses.append("product_code = ANY(:product_codes)")
            params["product_codes"] = filters.product_codes
        if filters.branches:
            clauses.append("branch = ANY(:branches)")
            params["branches"] = filters.branches
        if filters.departments:
            clauses.append("department = ANY(:departments)")
            params["departments"] = filters.departments
        if filters.search_text:
            clauses.append(
                "(product_code ILIKE :search OR branch ILIKE :search OR description ILIKE :search "
                "OR admin ILIKE :search OR buyer ILIKE :search)"
            )
            params["search"] = f"%{filters.search_text}%"

        where_sql = f"WHERE {' AND '.join(clauses)}"
        sql = text(
            f"""
            SELECT * FROM (
                SELECT DISTINCT ON (branch, product_code)
                    product_code,
                    branch,
                    department,
                    description,
                    admin,
                    buyer,
                    branch_product_period_start AS period_start,
                    branch_product_period_end AS period_end,
                    total_sales_qty,
                    total_pending_po,
                    average_daily_sales,
                    priority,
                    stock_lasts_until,
                    reorder_date,
                    reorder_status
                FROM mv_sales_fact
                {where_sql}
                ORDER BY branch, product_code, period_end DESC, period_start DESC
            ) collapsed
            ORDER BY total_sales_qty DESC
            LIMIT :limit
            """
        )
        result = self.session.execute(sql, params)
        return pd.DataFrame(result.mappings().all())

    def summary_counts(self, time_range: TimeRange = "ALL") -> dict[str, int]:
        row = self.session.execute(
            text(
                "SELECT COUNT(DISTINCT (branch, product_code)) AS total_rows, "
                "COUNT(DISTINCT product_code) AS products, "
                "COUNT(DISTINCT branch) AS branches, "
                "COUNT(DISTINCT department) AS departments "
                "FROM mv_sales_fact WHERE time_range = :time_range"
            ),
            {"time_range": time_range},
        ).mappings().first()
        return dict(row) if row else {"total_rows": 0, "products": 0, "branches": 0, "departments": 0}

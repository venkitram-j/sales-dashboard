from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class DashboardFilters:
    product_codes: list[str] | None = None
    branches: list[str] | None = None
    search_text: str | None = None
    limit: int = 5000


class DashboardService:
    """Reads from mv_sales_fact only -- never sales_fact directly -- so
    dashboard queries stay fast regardless of how large the base table gets.
    """

    def __init__(self, session: Session):
        self.session = session

    def get_distinct_product_codes(self) -> list[str]:
        rows = self.session.execute(
            text("SELECT DISTINCT product_code FROM mv_sales_fact ORDER BY product_code LIMIT 5000")
        )
        return [r[0] for r in rows]

    def get_distinct_branches(self) -> list[str]:
        rows = self.session.execute(
            text("SELECT DISTINCT branch FROM mv_sales_fact ORDER BY branch LIMIT 5000")
        )
        return [r[0] for r in rows]

    def query(self, filters: DashboardFilters) -> pd.DataFrame:
        clauses: list[str] = []
        params: dict[str, object] = {"limit": filters.limit}

        if filters.product_codes:
            clauses.append("product_code = ANY(:product_codes)")
            params["product_codes"] = filters.product_codes
        if filters.branches:
            clauses.append("branch = ANY(:branches)")
            params["branches"] = filters.branches
        if filters.search_text:
            clauses.append(
                "(product_code ILIKE :search OR branch ILIKE :search OR description ILIKE :search "
                "OR admin ILIKE :search OR buyer ILIKE :search)"
            )
            params["search"] = f"%{filters.search_text}%"

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = text(
            f"""
            SELECT 
                product_code AS "Product Code",
                description AS "Description",
                branch AS "Branch",
                sales_qty AS "Sales Quantity",
                pending_po AS "Pending PO",
                admin AS "Admin",
                buyer AS "Buyer"
            FROM mv_sales_fact
            {where_sql}
            ORDER BY sales_qty DESC
            LIMIT :limit
            """
        )
        result = self.session.execute(sql, params)
        return pd.DataFrame(result.mappings().all())

    def summary_counts(self) -> dict[str, int]:
        row = self.session.execute(
            text(
                "SELECT COUNT(*) AS total_rows, COUNT(DISTINCT product_code) AS products, "
                "COUNT(DISTINCT branch) AS branches FROM mv_sales_fact"
            )
        ).mappings().first()
        return dict(row) if row else {"total_rows": 0, "products": 0, "branches": 0}

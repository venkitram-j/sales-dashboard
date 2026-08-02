from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.product_supplier_lead_time import ProductSupplierLeadTime
from app.services.materialized_view_service import refresh_lead_time_view, refresh_sales_fact_view
from app.utils.column_normalization import normalize_column_name

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"product_code", "buyer", "lead_days"}


class LeadTimeUploadError(ValueError):
    pass


class LeadTimeService:
    def __init__(self, session: Session):
        self.session = session

    def parse_upload(self, file_path: Path, default_lead_days: int) -> pd.DataFrame:
        try:
            raw = pd.read_excel(file_path, engine="openpyxl")
        except Exception as exc:  # noqa: BLE001
            raise LeadTimeUploadError(f"Failed to read '{file_path.name}': {exc}") from exc

        raw.columns = [normalize_column_name(c) for c in raw.columns]
        missing = REQUIRED_COLUMNS - set(raw.columns)
        if missing:
            raise LeadTimeUploadError(
                f"Uploaded file is missing required column(s), expected columns: Product Code, Buyer, Lead Days."
            )

        df = raw[list(REQUIRED_COLUMNS)].copy()
        df = df[df["product_code"].notna()]
        df["product_code"] = df["product_code"].astype(str).str.strip()
        df["buyer"] = df["buyer"].astype(str).str.strip()
        df["lead_days"] = pd.to_numeric(df["lead_days"], errors="coerce").fillna(default_lead_days).astype(int)
        return df

    def replace_all(self, df: pd.DataFrame, refresh_view: bool = True) -> int:
        """Deletes all existing rows and bulk-inserts the new dataset
        (per spec: 'further uploads should delete all data ... and re-insert')."""
        self.session.execute(delete(ProductSupplierLeadTime))
        self.session.flush()

        records = [
            ProductSupplierLeadTime(
                product_code=row.product_code, buyer=row.buyer, lead_days=int(row.lead_days)
            )
            for row in df.itertuples(index=False)
        ]
        self.session.bulk_save_objects(records)
        self.session.flush()

        if refresh_view:
            refresh_lead_time_view(self.session)
            # mv_sales_fact's reorder_date/reorder_status columns depend on
            # product_supplier_lead_time (see the migration), so a lead
            # time change needs to propagate there too, not just to
            # mv_product_supplier_lead_time.
            refresh_sales_fact_view(self.session)

        logger.info("Replaced product_supplier_lead_time with %d rows", len(records))
        return len(records)

    def query_view(self) -> pd.DataFrame:
        """Reads display data from mv_product_supplier_lead_time, per spec."""
        result = self.session.execute(
            text(
                "SELECT id, product_code, buyer, lead_days, updated_at "
                "FROM mv_product_supplier_lead_time ORDER BY product_code, buyer"
            )
        )
        return pd.DataFrame(result.mappings().all())

    def get_all(self) -> list[ProductSupplierLeadTime]:
        return list(
            self.session.scalars(
                select(ProductSupplierLeadTime).order_by(ProductSupplierLeadTime.product_code)
            ).all()
        )

    def update_row(self, row_id: int, lead_days: int, refresh_view: bool = True) -> None:
        row = self.session.get(ProductSupplierLeadTime, row_id)
        if row is None:
            raise ValueError(f"No lead time row with id={row_id}")
        row.lead_days = lead_days
        self.session.flush()
        if refresh_view:
            refresh_lead_time_view(self.session)
            refresh_sales_fact_view(self.session)

    def update_many(self, updates: dict[int, int], refresh_view: bool = True) -> None:
        for row_id, lead_days in updates.items():
            row = self.session.get(ProductSupplierLeadTime, row_id)
            if row is not None and row.lead_days != lead_days:
                row.lead_days = lead_days
        self.session.flush()
        if refresh_view:
            refresh_lead_time_view(self.session)
            refresh_sales_fact_view(self.session)

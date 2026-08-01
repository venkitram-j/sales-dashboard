from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProductSupplierLeadTime(Base):
    """Lead time (in days) per product/buyer (supplier) mapping."""

    __tablename__ = "product_supplier_lead_time"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(100), nullable=False)
    buyer: Mapped[str] = mapped_column(String(200), nullable=False)
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("product_code", "buyer", name="uq_product_supplier"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProductSupplierLeadTime {self.product_code!r}/{self.buyer!r}={self.lead_days}>"

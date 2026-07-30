from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SalesFact(Base):
    """One row per (product_code, branch, ...) record parsed from a source
    Excel file. This table is expected to grow to millions of rows, so it
    only carries the columns needed and is indexed for the Dashboard's
    filter/search patterns. Reporting reads should go through the
    mv_sales_fact materialized view, not this table directly.
    """

    __tablename__ = "sales_fact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    sales_qty: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    pending_po: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    admin: Mapped[str | None] = mapped_column(String(200), nullable=True)
    buyer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_file: Mapped[str] = mapped_column(
        String(500),
        ForeignKey("ingested_files.file_name", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_sales_fact_product_code", "product_code"),
        Index("ix_sales_fact_branch", "branch"),
        Index("ix_sales_fact_source_file", "source_file"),
        Index("ix_sales_fact_product_branch", "product_code", "branch"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SalesFact product_code={self.product_code!r} branch={self.branch!r}>"

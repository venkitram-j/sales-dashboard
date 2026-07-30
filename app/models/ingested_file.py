from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IngestedFile(Base):
    """Tracks every Excel file that has been (successfully) ingested.

    file_name is referenced by SalesFact.source_file. file_mtime is compared
    against the file's on-disk modification time on each refresh to decide
    whether a file needs to be re-parsed.
    """

    __tablename__ = "ingested_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    file_mtime: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    ingested_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IngestedFile file_name={self.file_name!r} status={self.status!r}>"

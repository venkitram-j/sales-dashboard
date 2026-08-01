from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IngestedFile(Base):
    """Tracks every Excel file that has been successfully ingested.

    A row only ever exists here for a file that was fully and successfully
    parsed and bulk-loaded into sales_fact -- if ingestion fails partway
    through, the row (if one was created) is deleted rather than marked
    failed, so this table is always an accurate record of "what's actually
    in sales_fact right now" (see IngestionService.ingest_file).

    file_name is referenced by SalesFact.source_file. file_mtime is compared
    against the file's on-disk modification time on each refresh to decide
    whether a file needs to be re-parsed. period_start/period_end are parsed
    fresh from the file name each time (see app.utils.filename_parser) and
    stored per-row on sales_fact, not here.
    """

    __tablename__ = "ingested_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    file_mtime: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IngestedFile file_name={self.file_name!r} row_count={self.row_count}>"

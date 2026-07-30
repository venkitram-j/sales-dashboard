from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSetting(Base):
    """Key/value store for application settings.

    Deliberately modeled as key -> value (with a value_type tag for casting)
    rather than one column per setting. This lets new settings be introduced
    by adding an entry to SETTING_DEFINITIONS (see app.services.settings_service)
    without an Alembic migration to alter the table shape -- only a data
    migration (or first-run bootstrap) to insert the new row is needed.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppSetting key={self.key!r} value={self.value!r}>"

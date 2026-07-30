"""Settings service.

Defines every known application setting in one place (SETTING_DEFINITIONS).
To add a new setting in the future: add one entry to this dict and, if it
should show up in the sidebar/initial form, add a field for it in
app.views.settings_view. No schema migration is required because
app_settings is a key/value table.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)


def _to_str(value: Any) -> str:
    return "" if value is None else str(value)


def _identity(value: str) -> str:
    return value


def _non_empty_string(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Value must not be empty")
    return value.strip()


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    value_type: str  # "string" | "int" | "path"
    default: Any
    description: str
    caster: Callable[[str], Any]
    validator: Callable[[Any], Any] | None = None
    # Settings NOT reset when source_folder changes (source_folder itself is
    # always preserved as the field the user just edited).
    reset_on_source_folder_change: bool = True


SETTING_DEFINITIONS: dict[str, SettingDefinition] = {
    "source_folder": SettingDefinition(
        key="source_folder",
        label="Source Folder",
        value_type="path",
        default="",
        description="Folder path scanned for Excel files to ingest into sales_fact.",
        caster=_identity,
        validator=_non_empty_string,
        reset_on_source_folder_change=False,
    ),
    "header_row": SettingDefinition(
        key="header_row",
        label="Header Row",
        value_type="int",
        default=1,
        description="1-based row number where column headers live in each source Excel sheet.",
        caster=int,
    ),
    "start_col": SettingDefinition(
        key="start_col",
        label="Start Column",
        value_type="string",
        default="A",
        description="Excel column letter where data starts (e.g. 'A').",
        caster=_identity,
    ),
    "order_process_days": SettingDefinition(
        key="order_process_days",
        label="Order Process Days",
        value_type="int",
        default=0,
        description="Days required to process an order internally.",
        caster=int,
    ),
    "default_lead_days": SettingDefinition(
        key="default_lead_days",
        label="Default Lead Days",
        value_type="int",
        default=0,
        description="Default supplier lead time (days) used when a product/buyer has no explicit mapping.",
        caster=int,
    ),
    "order_buffer_high_days": SettingDefinition(
        key="order_buffer_high_days",
        label="Order Buffer (High) Days",
        value_type="int",
        default=0,
        description="Buffer days added for high-priority order classification.",
        caster=int,
    ),
    "order_buffer_medium_days": SettingDefinition(
        key="order_buffer_medium_days",
        label="Order Buffer (Medium) Days",
        value_type="int",
        default=0,
        description="Buffer days added for medium-priority order classification.",
        caster=int,
    ),
    "order_buffer_low_days": SettingDefinition(
        key="order_buffer_low_days",
        label="Order Buffer (Low) Days",
        value_type="int",
        default=0,
        description="Buffer days added for low-priority order classification.",
        caster=int,
    ),
}


class SettingsService:
    """Reads/writes app_settings, bootstraps defaults, exposes typed values."""

    def __init__(self, session: Session):
        self.session = session

    def bootstrap_defaults(self) -> None:
        """Ensure every defined setting has a row (idempotent)."""
        existing_keys = set(self.session.scalars(select(AppSetting.key)).all())
        created = False
        for definition in SETTING_DEFINITIONS.values():
            if definition.key not in existing_keys:
                self.session.add(
                    AppSetting(
                        key=definition.key,
                        value=_to_str(definition.default),
                        value_type=definition.value_type,
                        description=definition.description,
                    )
                )
                created = True
        if created:
            self.session.flush()
            logger.info("Bootstrapped missing app_settings defaults")

    def is_configured(self) -> bool:
        """True once source_folder has been set to a non-empty value."""
        row = self.session.scalar(select(AppSetting).where(AppSetting.key == "source_folder"))
        return bool(row and row.value and row.value.strip())

    def get_all(self) -> dict[str, Any]:
        rows = {row.key: row.value for row in self.session.scalars(select(AppSetting)).all()}
        result: dict[str, Any] = {}
        for key, definition in SETTING_DEFINITIONS.items():
            raw = rows.get(key)
            result[key] = definition.caster(raw) if raw is not None else definition.default
        return result

    def get(self, key: str) -> Any:
        definition = SETTING_DEFINITIONS[key]
        row = self.session.scalar(select(AppSetting).where(AppSetting.key == key))
        if row is None or row.value is None:
            return definition.default
        return definition.caster(row.value)

    def update(self, values: dict[str, Any]) -> None:
        """Validate and persist a batch of settings changes."""
        for key, raw_value in values.items():
            definition = SETTING_DEFINITIONS.get(key)
            if definition is None:
                logger.warning("Ignoring unknown setting key=%s", key)
                continue
            value = definition.validator(raw_value) if definition.validator else raw_value
            row = self.session.scalar(select(AppSetting).where(AppSetting.key == key))
            if row is None:
                row = AppSetting(key=key, value_type=definition.value_type)
                self.session.add(row)
            row.value = _to_str(value)
        self.session.flush()

    def reset_all_except(self, keep_keys: set[str]) -> None:
        """Reset every setting to its default except the given keys
        (used when source_folder changes -- see dashboard refresh flow)."""
        for key, definition in SETTING_DEFINITIONS.items():
            if key in keep_keys:
                continue
            row = self.session.scalar(select(AppSetting).where(AppSetting.key == key))
            if row is not None:
                row.value = _to_str(definition.default)
        self.session.flush()
        logger.info("Reset settings to defaults except: %s", keep_keys)

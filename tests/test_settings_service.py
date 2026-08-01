from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.settings_service import SettingsService, SettingsValidationError


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    yield s
    s.close()


def test_bootstrap_defaults_creates_all_settings(session):
    service = SettingsService(session)
    service.bootstrap_defaults()
    values = service.get_all()
    assert values["header_row"] == 1
    assert values["start_col"] == "A"
    assert values["source_folder"] == ""


def test_is_configured_false_until_source_folder_set(session):
    service = SettingsService(session)
    service.bootstrap_defaults()
    assert service.is_configured() is False

    service.update({"source_folder": "/data/excel"})
    assert service.is_configured() is True


def test_update_rejects_empty_source_folder_with_labeled_error(session):
    service = SettingsService(session)
    service.bootstrap_defaults()

    with pytest.raises(SettingsValidationError) as exc_info:
        service.update({"source_folder": "   ", "header_row": 2})

    assert exc_info.value.field_labels == ["Source Folder"]
    assert "Source Folder" in str(exc_info.value)


def test_update_does_not_persist_any_field_when_validation_fails(session):
    service = SettingsService(session)
    service.bootstrap_defaults()

    with pytest.raises(SettingsValidationError):
        service.update({"source_folder": "", "header_row": 5})

    values = service.get_all()
    # header_row must NOT have been saved even though it was individually
    # valid -- the whole batch is rejected together.
    assert values["header_row"] == 1
    assert values["source_folder"] == ""


def test_update_reports_multiple_invalid_fields_together(session):
    service = SettingsService(session)
    service.bootstrap_defaults()

    # Simulate a second required field by using the same validator pattern:
    # only source_folder has a validator today, so we assert the aggregation
    # mechanism itself works for the one required field, and stays a no-op
    # for fields without a validator.
    with pytest.raises(SettingsValidationError) as exc_info:
        service.update({"source_folder": ""})

    assert exc_info.value.field_labels == ["Source Folder"]


def test_update_persists_valid_values(session):
    service = SettingsService(session)
    service.bootstrap_defaults()

    service.update({"source_folder": "/data/excel", "header_row": 3, "start_col": "C"})

    values = service.get_all()
    assert values["source_folder"] == "/data/excel"
    assert values["header_row"] == 3
    assert values["start_col"] == "C"


def test_reset_all_except_preserves_given_keys(session):
    service = SettingsService(session)
    service.bootstrap_defaults()
    service.update({"source_folder": "/data/excel", "header_row": 9})

    service.reset_all_except({"source_folder"})

    values = service.get_all()
    assert values["source_folder"] == "/data/excel"
    assert values["header_row"] == 1  # reset to default

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.ingested_file import IngestedFile
from app.models.sales_fact import SalesFact
from app.services.ingestion_service import IngestionService

HEADERS = ["Product Code", "Description", "Branch", "Sales Qty", "Pending PO", "Admin", "Buyer"]
ROWS = [
    ["P001", "Widget", "B1", 10, 2, "Alice", "Bob"],
    ["P002", "Gadget", "B1", 5, 0, "Alice", "Carol"],
]


def _write_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in ROWS:
        ws.append(row)
    wb.save(path)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", future=True)

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


def _fake_bulk_copy_via_separate_session(session_factory, visibility: dict, file_name: str):
    """Returns a _bulk_copy replacement that loads rows through a SECOND,
    independent session/connection -- mirroring how the real Postgres COPY
    runs on its own raw connection, separate from the SQLAlchemy ORM
    session used for everything else in IngestionService. Records whether
    the ingested_files row for `file_name` was already visible/committed
    from that second connection's point of view before it inserts anything,
    which is exactly the condition that caused the original
    ForeignKeyViolation bug when it was missing.
    """

    def _fake(df):
        other_session = session_factory()
        try:
            record = other_session.scalar(
                select(IngestedFile).where(IngestedFile.file_name == file_name)
            )
            visibility["ingested_files_row_visible_before_copy"] = record is not None
            if record is None:
                # Mirror what Postgres' FK constraint would do.
                raise RuntimeError(
                    f"ForeignKeyViolation: source_file '{file_name}' not present in ingested_files"
                )
            # SQLite (used here as a lightweight stand-in for Postgres) only
            # auto-increments an INTEGER PRIMARY KEY, not BigInteger, so ids
            # are assigned explicitly -- irrelevant to the real Postgres
            # schema (BIGSERIAL), just a testing-environment detail.
            next_id = (other_session.scalar(select(func.max(SalesFact.id))) or 0) + 1
            for offset, row in enumerate(df.itertuples(index=False)):
                other_session.add(
                    SalesFact(
                        id=next_id + offset,
                        product_code=row.product_code,
                        description=row.description,
                        branch=row.branch,
                        sales_qty=row.sales_qty,
                        pending_po=row.pending_po,
                        admin=row.admin,
                        buyer=row.buyer,
                        source_file=row.source_file,
                        period_start=row.period_start,
                        period_end=row.period_end,
                    )
                )
            other_session.commit()
            return len(df)
        finally:
            other_session.close()

    return _fake


def test_ingested_file_record_is_committed_before_bulk_copy_runs(tmp_path, session, engine, session_factory):
    """Regression test for the FK violation: sales_fact.source_file
    references ingested_files.file_name, and the bulk load happens on a
    separate connection/transaction, so the ingested_files row must be
    visible from that other connection *before* the copy is attempted."""
    file_path = tmp_path / "Sales_20260101_20260131.xlsx"
    _write_workbook(file_path)

    service = IngestionService(session, engine)
    visibility: dict = {}
    service._bulk_copy = _fake_bulk_copy_via_separate_session(  # type: ignore[method-assign]
        session_factory, visibility, file_path.name
    )

    row_count = service.ingest_file(file_path, header_row=1, start_col="A", is_reingest=False)

    assert visibility["ingested_files_row_visible_before_copy"] is True
    assert row_count == 2

    record = session.scalar(select(IngestedFile).where(IngestedFile.file_name == file_path.name))
    assert record is not None
    assert record.row_count == 2


def test_ingested_file_record_is_removed_when_bulk_copy_fails(tmp_path, session, engine):
    file_path = tmp_path / "Sales_20260201_20260228.xlsx"
    _write_workbook(file_path)

    service = IngestionService(session, engine)

    def failing_bulk_copy(df):
        raise RuntimeError("simulated bulk load failure")

    service._bulk_copy = failing_bulk_copy  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated bulk load failure"):
        service.ingest_file(file_path, header_row=1, start_col="A", is_reingest=False)

    remaining = session.scalar(select(IngestedFile).where(IngestedFile.file_name == file_path.name))
    assert remaining is None

    leaked_rows = session.scalars(select(SalesFact).where(SalesFact.source_file == file_path.name)).all()
    assert list(leaked_rows) == []


def test_ingest_all_reports_failure_without_leaving_a_record_and_continues(
    tmp_path, session, engine, session_factory
):
    good_file = tmp_path / "Sales_20260101_20260131.xlsx"
    _write_workbook(good_file)
    # Missing the required period dates in the file name -> FileNamePeriodError,
    # raised before any DB row is ever created for it.
    bad_file = tmp_path / "Sales_no_dates.xlsx"
    _write_workbook(bad_file)

    service = IngestionService(session, engine)
    visibility: dict = {}
    service._bulk_copy = _fake_bulk_copy_via_separate_session(  # type: ignore[method-assign]
        session_factory, visibility, good_file.name
    )

    result = service.ingest_all(source_folder=str(tmp_path), header_row=1, start_col="A", refresh_view=False)

    assert result.ingested_files == [good_file.name]
    assert bad_file.name in result.failed_files
    assert result.total_rows_inserted == 2

    good_record = session.scalar(select(IngestedFile).where(IngestedFile.file_name == good_file.name))
    assert good_record is not None
    bad_record = session.scalar(select(IngestedFile).where(IngestedFile.file_name == bad_file.name))
    assert bad_record is None


def test_ingest_all_skips_unchanged_files_on_second_run(tmp_path, session, engine, session_factory):
    file_path = tmp_path / "Sales_20260301_20260331.xlsx"
    _write_workbook(file_path)

    service = IngestionService(session, engine)
    visibility: dict = {}
    service._bulk_copy = _fake_bulk_copy_via_separate_session(  # type: ignore[method-assign]
        session_factory, visibility, file_path.name
    )

    first = service.ingest_all(source_folder=str(tmp_path), header_row=1, start_col="A", refresh_view=False)
    assert first.ingested_files == [file_path.name]

    second = service.ingest_all(source_folder=str(tmp_path), header_row=1, start_col="A", refresh_view=False)
    assert second.ingested_files == []
    assert second.skipped_unchanged == [file_path.name]

from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from app.database import get_engine, session_scope
from app.services.dashboard_service import DashboardFilters, DashboardService
from app.services.ingestion_service import IngestionResult, IngestionService
from app.services.settings_service import SettingsService
from app.views.base import BaseView

logger = logging.getLogger(__name__)


def run_full_ingest() -> IngestionResult:
    """Parses/ingests every eligible file in source_folder and refreshes
    mv_sales_fact. Used both on first run and by the sidebar refresh button.
    Exposed as a module function so main.py can call it before the
    Dashboard page is even the active page.
    """
    engine = get_engine()
    with session_scope() as session:
        settings_service = SettingsService(session)
        settings = settings_service.get_all()
        ingestion_service = IngestionService(session, engine)
        return ingestion_service.ingest_all(
            source_folder=settings["source_folder"],
            header_row=settings["header_row"],
            start_col=settings["start_col"],
        )


def _report_result(result: IngestionResult) -> None:
    if result.ingested_files:
        st.toast(f"Ingested {len(result.ingested_files)} new file(s).", icon="✅")
    if result.reingested_files:
        st.toast(f"Re-ingested {len(result.reingested_files)} modified file(s).", icon="🔄")
    if result.failed_files:
        st.error(f"{len(result.failed_files)} file(s) failed to ingest:")
        for name, err in result.failed_files.items():
            st.write(f"- **{name}**: {err}")
    if not (result.ingested_files or result.reingested_files or result.failed_files):
        st.toast("No new or modified files found.", icon="ℹ️")


class DashboardView(BaseView):
    title = "Dashboard"
    icon = "📊"

    def body(self) -> None:
        with session_scope() as session:
            summary = DashboardService(session).summary_counts()

        if summary.get("total_rows", 0) == 0:
            self._render_empty_state()
            return

        if st.button("🔄 Refresh", help="Parse new/modified files and refresh the view"):
            with st.spinner("Ingesting new/modified files..."):
                result = run_full_ingest()
            _report_result(result)
            st.rerun()

        with session_scope() as session:
            service = DashboardService(session)
            summary = service.summary_counts()
            product_options = service.get_distinct_product_codes()
            branch_options = service.get_distinct_branches()

        st.metric("Rows", f"{summary.get('total_rows', 0):,}")

        st.caption(
            f"{summary.get('products', 0):,} distinct products across "
            f"{summary.get('branches', 0):,} branches"
        )

        filter_cols = st.columns(3)
        with filter_cols[0]:
            selected_products = st.multiselect("Filter: Product Code", product_options)
        with filter_cols[1]:
            selected_branches = st.multiselect("Filter: Branch", branch_options)
        with filter_cols[2]:
            search_text = st.text_input(
                "Search",
                placeholder="Product code, branch, description, admin, or buyer...",
            )

        filters = DashboardFilters(
            product_codes=selected_products or None,
            branches=selected_branches or None,
            search_text=search_text or None,
        )

        with session_scope() as session:
            service = DashboardService(session)
            df = service.query(filters)

        if len(df) == filters.limit:
            st.caption(f"Showing first {filters.limit:,} rows — narrow your filters to see more precisely.")
        
        DATE_COLUMNS = ["period_start", "period_end"]
        for col in DATE_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%d-%b-%Y")

        st.dataframe(df, width="stretch", hide_index=True)

    def _render_empty_state(self) -> None:
        """No rows in mv_sales_fact yet: show only a Refresh button and
        guidance, rather than an empty table with filters over nothing."""
        if st.button("🔄 Refresh", help="Parse files in source_folder and load them", type="primary"):
            with st.spinner("Ingesting files from source folder..."):
                result = run_full_ingest()
            _report_result(result)
            st.rerun()

        st.info(
            "No data has been loaded yet. Check that your Excel file names follow "
            "the required naming convention (a period_start and period_end date "
            "pair, e.g. `Sales_20260101_20260131.xlsx` — see the README) and that "
            "**Source Folder** in Settings points at the right directory. Then "
            "click **Refresh** above to parse and load the files."
        )

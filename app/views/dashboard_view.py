from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from app.database import get_engine, session_scope
from app.services.dashboard_service import TIME_RANGE_OPTIONS, DashboardFilters, DashboardService
from app.services.ingestion_service import IngestionResult, IngestionService
from app.services.settings_service import SettingsService
from app.utils.ui import blocking_button
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
            # "Any data at all" is checked against the broadest bucket
            # ('ALL') regardless of whatever time range the user might
            # pick below -- a narrower window legitimately can be empty
            # even when data exists overall.
            overall_summary = DashboardService(session).summary_counts(time_range="ALL")

        if overall_summary.get("total_rows", 0) == 0:
            self._render_empty_state()
            return

        top = st.columns([1, 1, 1, 5])
        with top[0]:
            if blocking_button(
                "🔄 Refresh", "dashboard_refreshing", help="Parse new/modified files and refresh the view"
            ):
                with st.spinner("Ingesting new/modified files..."):
                    result = run_full_ingest()
                _report_result(result)
                st.session_state["dashboard_refreshing"] = False
                st.rerun()

        with top[1]:
            time_range_label = st.selectbox(
                "Time Range",
                options=list(TIME_RANGE_OPTIONS.keys()),
                help="Aggregates (sales, priority, reorder planning) are computed over this window.",
                label_visibility="collapsed",
            )
        time_range = TIME_RANGE_OPTIONS[time_range_label]

        with session_scope() as session:
            service = DashboardService(session)
            summary = service.summary_counts(time_range=time_range)
            product_options = service.get_distinct_product_codes(time_range=time_range)
            branch_options = service.get_distinct_branches(time_range=time_range)
            department_options = service.get_distinct_departments(time_range=time_range)

        st.metric("Branch/Products", f"{summary.get('total_rows', 0):,}")

        st.caption(
            f"{summary.get('products', 0):,} distinct products across "
            f"{summary.get('branches', 0):,} branches "
            f"under {summary.get('departments', 0)} departments — {time_range_label.lower()}"
        )

        if summary.get("total_rows", 0) == 0:
            st.info(f"No data falls within **{time_range_label}**. Try a wider time range.")
            return

        filter_cols = st.columns(3)
        with filter_cols[0]:
            selected_products = st.multiselect("Filter: Product Code", product_options)
        with filter_cols[1]:
            selected_branches = st.multiselect("Filter: Branch", branch_options)
        with filter_cols[2]:
            selected_departments = st.multiselect("Filter: Department", department_options)
        
        search_text = st.text_input(
            "Search",
            placeholder="Product Code, Branch, Description, Admin, or Buyer...",
        )

        filters = DashboardFilters(
            time_range=time_range,
            product_codes=selected_products or None,
            branches=selected_branches or None,
            departments=selected_departments or None,
            search_text=search_text or None,
        )

        with session_scope() as session:
            service = DashboardService(session)
            df = service.query(filters)

        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "product_code": st.column_config.TextColumn("Product Code"),
                "branch": st.column_config.TextColumn("Branch"),
                "department": st.column_config.TextColumn("Department"),
                "description": st.column_config.TextColumn("Description"),
                "admin": st.column_config.TextColumn("Admin"),
                "buyer": st.column_config.TextColumn("Buyer"),
                "reorder_status": st.column_config.TextColumn("Reorder Status"),
                "priority": st.column_config.TextColumn("Priority"),
                "total_sales_qty": st.column_config.NumberColumn("Total Sales Qty", format="%.2f"),
                "total_pending_po": st.column_config.NumberColumn("Total Pending PO", format="%.2f"),
                "average_daily_sales": st.column_config.NumberColumn("Avg Daily Sales", format="%.2f"),
                "stock_lasts_until": st.column_config.DateColumn("Stock Lasts Until"),
                "reorder_date": st.column_config.DateColumn("Reorder Date"),
                "period_start": st.column_config.DateColumn("Period Start"),
                "period_end": st.column_config.DateColumn("Period End"),
            },
        )
        if len(df) == filters.limit:
            st.caption(f"Showing first {filters.limit:,} rows — narrow your filters to see more precisely.")

    def _render_empty_state(self) -> None:
        """No rows in mv_sales_fact yet: show only a Refresh button and
        guidance, rather than an empty table with filters over nothing."""
        if blocking_button(
            "🔄 Refresh", "dashboard_refreshing", help="Parse files in source_folder and load them"
        ):
            with st.spinner("Ingesting files from source_folder..."):
                result = run_full_ingest()
            _report_result(result)
            st.session_state["dashboard_refreshing"] = False
            st.rerun()

        st.info(
            "No data has been loaded yet. Check that your Excel file names follow "
            "the required naming convention (a period_start and period_end date "
            "pair, e.g. `Sales_20260101_20260131.xlsx` — see the README) and that "
            "**Source Folder** in Settings points at the right directory. Then "
            "click **Refresh** above to parse and load the files."
        )

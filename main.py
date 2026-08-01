"""App entrypoint.

Run with: streamlit run main.py

Lifecycle:
  1. Bootstrap logging + ensure app_settings has default rows.
  2. If source_folder has never been set, show the mandatory initial setup
     form full-page and stop (nothing else loads).
  3. Once configured: react to any pending settings changes from the
     sidebar (full reset+re-ingest if source_folder changed, otherwise a
     lightweight materialized-view refresh), render the sidebar settings
     form, then the selected page.

Navigation: st.navigation() is called exactly once per script run, with a
page list built from the current config state (Initial-Setup-only before
`source_folder` is configured, Dashboard+Lead Time once it is). This is
Streamlit's own documented pattern for state-dependent multipage apps --
see https://docs.streamlit.io/develop/concepts/multipage-apps/page-and-navigation.
"""
from __future__ import annotations

import logging

import streamlit as st

from app.config import get_settings
from app.database import get_engine, session_scope
from app.services.ingestion_service import IngestionService
from app.services.materialized_view_service import refresh_sales_fact_view
from app.services.settings_service import SettingsService
from app.utils.logging_config import configure_logging
from app.views.dashboard_view import DashboardView, _report_result, run_full_ingest
from app.views.lead_time_view import LeadTimeView
from app.views.settings_view import SettingsView

configure_logging()
logger = logging.getLogger(__name__)


def _initial_setup_page() -> None:
    settings_view = SettingsView()
    just_configured = settings_view.render_initial_setup()
    if just_configured:
        with st.spinner("Running initial ingestion of all files in source_folder..."):
            result = run_full_ingest()
        _report_result(result)
        st.session_state["settings_just_saved"] = False
        st.session_state["source_folder_changed"] = False
        st.rerun()


def _dashboard_page() -> None:
    DashboardView().render()


def _lead_time_page() -> None:
    LeadTimeView().render()


def _handle_pending_settings_change() -> None:
    """Reacts to a settings save that happened on the previous rerun
    (flags set by SettingsView.render_sidebar)."""
    if not st.session_state.get("settings_just_saved"):
        return

    source_folder_changed = st.session_state.get("source_folder_changed", False)

    if source_folder_changed:
        st.warning(
            "Source folder changed — resetting sales data and other settings, "
            "then re-ingesting from the new folder."
        )
        engine = get_engine()
        with session_scope() as session:
            settings_service = SettingsService(session)
            settings_service.reset_all_except({"source_folder"})
            ingestion_service = IngestionService(session, engine)
            ingestion_service.reset_all_sales_data()

        with st.spinner("Re-ingesting from new source folder..."):
            result = run_full_ingest()
        _report_result(result)
    else:
        with st.spinner("Refreshing dashboard view..."):
            with session_scope() as session:
                refresh_sales_fact_view(session)

    st.session_state["settings_just_saved"] = False
    st.session_state["source_folder_changed"] = False


def main() -> None:
    app_settings = get_settings()
    st.set_page_config(
        page_title="Sales Dashboard",
        page_icon="📦",
        layout="wide",
    )

    with session_scope() as session:
        settings_service = SettingsService(session)
        settings_service.bootstrap_defaults()
        configured = settings_service.is_configured()

    # Build the page set for *this* run from current config state, and call
    # st.navigation() exactly once, every run -- see module docstring.
    if not configured:
        pages = [st.Page(_initial_setup_page, title="Initial Setup", icon="⚙️", default=True)]
    else:
        _handle_pending_settings_change()
        SettingsView().render_sidebar()
        pages = [
            st.Page(_dashboard_page, title="Dashboard", icon="📊", default=True),
            st.Page(_lead_time_page, title="Product-Supplier Lead Time", icon="🚚"),
        ]

    navigation = st.navigation(pages)
    navigation.run()


if __name__ == "__main__":
    main()

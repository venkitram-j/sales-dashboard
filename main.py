"""App entrypoint.

Run with: streamlit run main.py

Lifecycle:
  1. Bootstrap logging.
  2. Authentication gate: an unauthenticated user only ever sees the Login
     page (app.views.login_view.LoginView). Nothing else renders until
     they log in successfully.
  3. Once authenticated: ensure app_settings has default rows. If
     source_folder has never been set, show the mandatory initial setup
     form full-page and stop (nothing else loads).
  4. Once configured: react to any pending settings changes from the
     sidebar (full reset+re-ingest if source_folder changed, otherwise a
     lightweight materialized-view refresh), render the top bar
     (username + logout) and the sidebar settings form, then the selected
     page.
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
from app.views.login_view import LoginView, try_auto_login
from app.views.settings_view import SettingsView
from app.views.topbar import render_topbar

configure_logging()
logger = logging.getLogger(__name__)


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
    logger.debug("App running in %s mode", app_settings.app_env)

    if not try_auto_login():
        LoginView().render()
        st.stop()

    with session_scope() as session:
        settings_service = SettingsService(session)
        settings_service.bootstrap_defaults()
        configured = settings_service.is_configured()

    if not configured:
        render_topbar()
        settings_view = SettingsView()
        just_configured = settings_view.render_initial_setup()
        if just_configured:
            with st.spinner("Running initial ingestion of all files in source_folder..."):
                result = run_full_ingest()
            _report_result(result)
            st.session_state["settings_just_saved"] = False
            st.session_state["source_folder_changed"] = False
            st.rerun()
        st.stop()

    _handle_pending_settings_change()

    render_topbar()
    SettingsView().render_sidebar()

    pages = [
        st.Page(_dashboard_page, title="Dashboard", icon="📊", default=True),
        st.Page(_lead_time_page, title="Product-Supplier Lead Time", icon="🚚"),
    ]
    navigation = st.navigation(pages)
    navigation.run()


if __name__ == "__main__":
    main()

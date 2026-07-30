"""Settings page/sidebar.

Two entry points, both used by main.py:
  - render_initial_setup(): full-page form shown once, before the source
    folder has ever been configured. Nothing else in the app loads until
    this is submitted successfully.
  - render_sidebar(): compact form always shown in the sidebar afterwards,
    letting the user tweak settings at any time. Sets
    st.session_state['source_folder_changed'] so main.py knows to trigger a
    full data reset + re-ingest versus a lightweight view refresh.
"""
from __future__ import annotations

import logging

import streamlit as st

from app.database import session_scope
from app.services.settings_service import SETTING_DEFINITIONS, SettingsService

logger = logging.getLogger(__name__)

_INT_KEYS = [k for k, d in SETTING_DEFINITIONS.items() if d.value_type == "int"]
_PATH_STRING_KEYS = [
    k for k, d in SETTING_DEFINITIONS.items() if d.value_type in ("path", "string")
]


class SettingsView:
    def render_initial_setup(self) -> bool:
        """Renders the mandatory first-run form. Returns True once the user
        has successfully submitted it (caller should st.rerun())."""
        st.title("Welcome — Initial Setup")
        st.info(
            "Before the app can load, tell it where to find your sales Excel "
            "files and how those files are laid out."
        )

        with st.form("initial_settings_form", border=True):
            values = self._render_fields(defaults=None)
            submitted = st.form_submit_button("Save & Continue", type="primary")

        if submitted:
            return self._save(values, is_initial=True)
        return False

    def render_sidebar(self) -> None:
        with session_scope() as session:
            service = SettingsService(session)
            current = service.get_all()

        with st.sidebar:
            st.header("Settings")
            with st.form("sidebar_settings_form", border=True):
                values = self._render_fields(defaults=current)
                submitted = st.form_submit_button("Save Settings", type="primary")

            if submitted:
                previous_folder = current["source_folder"]
                saved = self._save(values, is_initial=False)
                if saved:
                    st.session_state["source_folder_changed"] = (
                        values["source_folder"] != previous_folder
                    )
                    st.session_state["settings_just_saved"] = True
                    st.rerun()

    # -- shared field rendering -----------------------------------------------
    def _render_fields(self, defaults: dict | None) -> dict:
        defaults = defaults or {k: d.default for k, d in SETTING_DEFINITIONS.items()}
        values: dict = {}
        values["source_folder"] = st.text_input(
            SETTING_DEFINITIONS["source_folder"].label,
            value=str(defaults["source_folder"]),
            help=SETTING_DEFINITIONS["source_folder"].description,
            placeholder="/path/to/excel/files",
        )
        values["header_row"] = st.number_input(
            SETTING_DEFINITIONS["header_row"].label,
            min_value=1,
            value=int(defaults["header_row"]),
            step=1,
            help=SETTING_DEFINITIONS["header_row"].description,
        )
        values["start_col"] = st.text_input(
            SETTING_DEFINITIONS["start_col"].label,
            value=str(defaults["start_col"]),
            help=SETTING_DEFINITIONS["start_col"].description,
            max_chars=3,
        )

        cols = st.columns(2)
        int_keys_rest = [k for k in _INT_KEYS if k != "header_row"]
        for i, key in enumerate(int_keys_rest):
            definition = SETTING_DEFINITIONS[key]
            with cols[i % 2]:
                values[key] = st.number_input(
                    definition.label,
                    min_value=0,
                    value=int(defaults[key]),
                    step=1,
                    help=definition.description,
                )
        return values

    def _save(self, values: dict, is_initial: bool) -> bool:
        try:
            with session_scope() as session:
                service = SettingsService(session)
                service.bootstrap_defaults()
                service.update(values)
            st.success("Settings saved.")
            return True
        except ValueError as exc:
            st.error(str(exc))
            return False
        except Exception:  # noqa: BLE001
            logger.exception("Failed to save settings")
            st.error("Failed to save settings. Check the logs for details.")
            return False

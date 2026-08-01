from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import streamlit as st

from app.database import session_scope
from app.services.lead_time_service import LeadTimeService, LeadTimeUploadError
from app.services.settings_service import SettingsService
from app.utils.ui import blocking_button
from app.views.base import BaseView

logger = logging.getLogger(__name__)


class LeadTimeView(BaseView):
    title = "Product-Supplier Lead Time"
    icon = "🚚"

    def body(self) -> None:
        self._render_update_form()
        st.divider()
        self._render_upload_section()

    # -- update form (edits existing mappings) --------------------------------
    def _render_update_form(self) -> None:
        st.subheader("Update Existing Lead Times")

        with session_scope() as session:
            service = LeadTimeService(session)
            df = service.query_view()

        if df.empty:
            st.info("No product-supplier lead time data yet. Upload a file below to get started.")
            return

        edited = st.data_editor(
            df,
            key="lead_time_editor",
            width="stretch",
            hide_index=True,
            disabled=["id", "product_code", "buyer", "updated_at"],
            column_config={
                "lead_days": st.column_config.NumberColumn("Lead Days", min_value=0, step=1),
            },
        )

        if blocking_button("Save Changes", "lead_time_saving", type="primary"):
            changes = {
                int(row.id): int(row.lead_days)
                for row in edited.itertuples(index=False)
            }
            try:
                with session_scope() as session:
                    service = LeadTimeService(session)
                    service.update_many(changes)
                st.success("Lead times updated.")
                st.session_state["lead_time_saving"] = False
                st.rerun()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to update lead times")
                st.error("Failed to save changes. Check the logs for details.")
                # Don't rerun here -- it would wipe the error above before
                # the user can read it. The button re-renders enabled on
                # whatever interaction happens next.
                st.session_state["lead_time_saving"] = False

    # -- bulk upload (replaces the whole table) --------------------------------
    def _render_upload_section(self) -> None:
        st.subheader("Upload Lead Time File")
        st.caption(
            "Uploading a file replaces **all** existing product-supplier lead time "
            "data. Expected columns: Product Code, Buyer, Lead Days."
        )
        uploaded = st.file_uploader("Excel file", type=["xlsx", "xlsm"], key="lead_time_upload")

        if blocking_button(
            "Process Upload", "lead_time_uploading", also_disabled=uploaded is None, type="primary"
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir) / uploaded.name
                tmp_path.write_bytes(uploaded.getvalue())

                try:
                    with session_scope() as session:
                        settings_service = SettingsService(session)
                        default_lead_days = settings_service.get("default_lead_days")
                        service = LeadTimeService(session)
                        df = service.parse_upload(tmp_path, default_lead_days=default_lead_days)
                        count = service.replace_all(df)
                    st.success(f"Replaced lead time data with {count:,} row(s).")
                    st.session_state["lead_time_uploading"] = False
                    st.rerun()
                except LeadTimeUploadError as exc:
                    st.error(str(exc))
                    # No rerun -- keep the error visible; button re-enables
                    # on whatever interaction happens next.
                    st.session_state["lead_time_uploading"] = False
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to process lead time upload")
                    st.error("Failed to process the upload. Check the logs for details.")
                    st.session_state["lead_time_uploading"] = False

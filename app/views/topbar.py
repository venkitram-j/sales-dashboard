"""Shared top bar: current username + logout button, right-aligned.

Rendered once per page (from main.py) above the page's own content, so the
"who's logged in" + logout affordance required on the Dashboard is present
on every authenticated page for consistency.
"""
from __future__ import annotations

import logging

import streamlit as st

from app.views.login_view import current_username, log_out

logger = logging.getLogger(__name__)


def render_topbar() -> None:
    _, user_col, logout_col = st.columns([6, 3, 1])
    with user_col:
        st.markdown(
            f"<div style='text-align:right; padding-top:0.5rem;'>"
            f"Logged in as <b>{current_username()}</b></div>",
            unsafe_allow_html=True,
        )
    with logout_col:
        if st.button("Log out", width="stretch"):
            username = current_username()
            log_out()
            logger.info("User logged out: username=%s", username)
            st.rerun()

"""Browser cookie helpers for the 'remember me' feature.

Reading uses st.context.cookies -- built into Streamlit itself (no extra
dependency), read-only, and reflects whatever cookies the browser sent with
the current page load/connection.

Writing has no native Streamlit API yet (see streamlit/streamlit#9421), so
a tiny inline <script> tag (via st.components.v1.html) sets document.cookie
directly. This avoids depending on a third-party cookie component's exact
(and sometimes flaky/undocumented) behavior for something this simple, in
keeping with 'use builtin Streamlit functions wherever possible'.
"""
from __future__ import annotations

import logging

import streamlit as st
import streamlit.components.v1 as components

from app.config import get_settings

logger = logging.getLogger(__name__)


def get_cookie(name: str) -> str | None:
    """Reads a cookie sent with the current request. Returns None if
    absent or if st.context.cookies can't be read for any reason."""
    try:
        return st.context.cookies.get(name)
    except Exception:  # noqa: BLE001 - defensive; keep the app usable
        logger.exception("Failed to read cookies from st.context")
        return None


def set_cookie(name: str, value: str, max_age_seconds: int) -> None:
    """Sets a cookie in the browser via an inline script. Takes effect for
    the browser's next page load/connection (st.context.cookies won't see
    it mid-session, since Streamlit reruns don't re-send request headers)."""
    secure_flag = "; Secure" if get_settings().is_production else ""
    components.html(
        f"""
        <script>
        document.cookie =
            "{name}={value}; path=/; max-age={max_age_seconds}; SameSite=Lax{secure_flag}";
        </script>
        """,
        height=0,
        width=0,
    )


def clear_cookie(name: str) -> None:
    components.html(
        f"""
        <script>
        document.cookie = "{name}=; path=/; max-age=0; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )

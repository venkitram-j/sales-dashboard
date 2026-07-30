"""Login page.

The only page in the Authentication component. On success it stores the
username/id in st.session_state and reruns; main.py reads that session
state to decide whether the user is authenticated and, if so, whether to
show the initial settings form or the normal app (see main.py).

'Remember me' persists login across browser restarts: a random session
token is created (app.services.auth_service.AuthService.create_session),
its hash is stored server-side in user_sessions, and the raw token is set
as a browser cookie (app.utils.cookies). try_auto_login() checks that
cookie on future page loads and silently re-authenticates the session if
it's still valid.
"""
from __future__ import annotations

import logging

import streamlit as st

from app.config import get_settings
from app.database import session_scope
from app.services.auth_service import AuthService
from app.utils.cookies import clear_cookie, get_cookie, set_cookie
from app.views.base import BaseView

logger = logging.getLogger(__name__)

SESSION_KEY_USERNAME = "auth_username"
SESSION_KEY_USER_ID = "auth_user_id"
SESSION_COOKIE_NAME = "sales_dashboard_session"


def is_authenticated() -> bool:
    return bool(st.session_state.get(SESSION_KEY_USERNAME))


def current_username() -> str | None:
    return st.session_state.get(SESSION_KEY_USERNAME)


def try_auto_login() -> bool:
    """If the current Streamlit session isn't already authenticated, checks
    for a valid 'remember me' cookie and silently signs the user back in.
    Returns True if the session is authenticated by the time this returns
    (whether it already was, or was just auto-logged-in)."""
    if is_authenticated():
        return True

    token = get_cookie(SESSION_COOKIE_NAME)
    if not token:
        return False

    with session_scope() as session:
        user = AuthService(session).validate_session(token)

    if user is None:
        # Stale, expired, or revoked token -- stop sending it.
        clear_cookie(SESSION_COOKIE_NAME)
        return False

    st.session_state[SESSION_KEY_USERNAME] = user.username
    st.session_state[SESSION_KEY_USER_ID] = user.id
    logger.info("Auto-logged in username=%s via remember-me cookie", user.username)
    return True


def log_out() -> None:
    """Clears the current session state and, if a remember-me cookie is
    present, revokes it server-side and removes it from the browser."""
    token = get_cookie(SESSION_COOKIE_NAME)
    if token:
        with session_scope() as session:
            AuthService(session).revoke_session(token)
        clear_cookie(SESSION_COOKIE_NAME)

    st.session_state.pop(SESSION_KEY_USERNAME, None)
    st.session_state.pop(SESSION_KEY_USER_ID, None)


class LoginView(BaseView):
    title = "Log In"
    icon = "🔐"

    def body(self) -> None:
        _, center, _ = st.columns([1, 2, 1])
        with center:
            st.caption("Sign in to continue to the Sales Dashboard App.")
            with st.form("login_form", border=True):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                remember_me = st.checkbox("Remember me on this device")
                submitted = st.form_submit_button("Log In", type="primary", width="stretch")

            if submitted:
                self._attempt_login(username, password, remember_me)

    def _attempt_login(self, username: str, password: str, remember_me: bool) -> None:
        if not username or not password:
            st.error("Enter both a username and a password.")
            return

        settings = get_settings()
        raw_token: str | None = None
        try:
            with session_scope() as session:
                auth_service = AuthService(session)
                user = auth_service.authenticate(username, password)
                if user is None:
                    st.error("Invalid username or password.")
                    return
                if remember_me:
                    raw_token = auth_service.create_session(user, ttl_days=settings.remember_me_days)
                user_id, user_username = user.id, user.username
        except Exception:  # noqa: BLE001
            logger.exception("Login attempt raised an unexpected error")
            st.error("Something went wrong while logging in. Check the logs for details.")
            return

        st.session_state[SESSION_KEY_USERNAME] = user_username
        st.session_state[SESSION_KEY_USER_ID] = user_id

        if raw_token:
            set_cookie(
                SESSION_COOKIE_NAME,
                raw_token,
                max_age_seconds=settings.remember_me_days * 24 * 60 * 60,
            )

        st.rerun()

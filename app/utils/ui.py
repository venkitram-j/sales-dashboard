"""UI helpers shared across views."""
from __future__ import annotations

import streamlit as st


def blocking_button(label: str, busy_key: str, also_disabled: bool = False, **kwargs) -> bool:
    """A button that disables itself for the duration of whatever the
    caller does after it returns True, so a double-click can't kick off
    the same (potentially slow) action twice.

    A single script run can't render a button, then change it to
    "disabled", then run a slow action, then change it back -- Streamlit
    only shows what a run looked like once that run finishes. So this
    takes two runs: the click sets a "busy" flag in session_state and
    immediately reruns (rendering the button disabled); since busy is now
    True, this function returns True on that second run, and the caller
    does the actual work.

    `also_disabled` lets the caller combine another condition (e.g. "no
    file uploaded yet") with the busy state -- the button is disabled if
    either is true, but only the busy flag ever triggers the rerun/return
    True cycle.

    Usage:
        if blocking_button("Refresh", "dashboard_refreshing"):
            do_the_slow_thing()
            st.session_state["dashboard_refreshing"] = False
            st.rerun()

    The caller MUST reset st.session_state[busy_key] to False once the
    action finishes -- on both success and failure -- or the button stays
    disabled.
    """
    busy = st.session_state.get(busy_key, False)
    clicked = st.button(label, disabled=busy or also_disabled, **kwargs)
    if clicked and not busy:
        st.session_state[busy_key] = True
        st.rerun()
    return busy

"""Base class for every page in the app.

Each page is a class with a render() method, giving pages a consistent
lifecycle (title, session handling, error boundary) instead of ad-hoc
top-to-bottom scripts. Subclasses implement `body()`; `render()` wraps it
with a page title and a shared error boundary so one page's exception
doesn't take down the whole app with a raw traceback.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import streamlit as st

logger = logging.getLogger(__name__)


class BaseView(ABC):
    title: str = "Untitled Page"
    icon: str | None = None

    @abstractmethod
    def body(self) -> None:
        """Subclasses implement the page content here."""

    def render(self) -> None:
        st.title(self.title)
        try:
            self.body()
        except Exception as exc:  # noqa: BLE001 - user-facing error boundary
            logger.exception("Unhandled error rendering view %s", type(self).__name__)
            st.error(f"Something went wrong while rendering this page: {exc}")
            with st.expander("Details"):
                st.exception(exc)

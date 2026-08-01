"""SQLAlchemy engine/session management.

A single process-wide engine is created lazily and cached via
st.cache_resource so every Streamlit rerun reuses the same connection pool
instead of opening new connections on every script execution.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import streamlit as st
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    settings = get_settings()
    logger.info("Creating SQLAlchemy engine for %s", settings.db_name)
    return create_engine(
        settings.sqlalchemy_database_uri,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        future=True,
    )


@st.cache_resource(show_spinner=False)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Usage:
        with session_scope() as session:
            session.add(obj)
    Commits on success, rolls back on exception, always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Session rolled back due to an exception")
        raise
    finally:
        session.close()

"""Postgres connection pooling shared by ingest.py and dashboard_app.py.

Kept free of any Streamlit dependency so ingest.py can run standalone
(e.g. from cron) without importing Streamlit at all.
"""

from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.pool

import config

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=10, dsn=config.DATABASE_URL
        )
    return _pool


@contextmanager
def get_conn():
    """Yield a pooled connection. Caller is responsible for commit/rollback."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def init_schema():
    """Create tables/indexes if they don't exist yet. Safe to call repeatedly."""
    schema_path = Path(__file__).parent / "schema.sql"
    ddl = schema_path.read_text()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()

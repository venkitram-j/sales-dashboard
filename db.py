"""
Postgres connection pooling
"""
import os

from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.pool

_pool = None


def get_pool():
    global _pool
    db_url = os.getenv("DATABASE_URL")
    if _pool is None:
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set.")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=10, dsn=db_url
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


# ---------------------------------------------------------------------------
# app_settings — operational ingestion config (source folder, header row,
# start column, order process time, default lead time, order buffers for high, medium
# and low priority products), editable from the dashboard instead of
# living in .env. DATABASE_URL and APP_PASSWORD stay in .env since they're
# needed to reach the database in the first place.
# ---------------------------------------------------------------------------

SETTINGS_KEYS = (
    "source_folder", "header_row", "start_col", "order_process_days", "default_lead_days",
    "order_buffer_high_days", "order_buffer_medium_days", "order_buffer_low_days"
)


def get_settings():
    """Return a dict with all settings. Missing keys come back as 
    None (header_row) or "" (the rest) so callers don't need to
    guard against KeyError."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM app_settings WHERE key = ANY(%s)", (list(SETTINGS_KEYS),))
            rows = dict(cur.fetchall())

    return {
        "source_folder": rows.get("source_folder") or "",
        "header_row": int(rows["header_row"]) if rows.get("header_row") else 1,
        "start_col": rows.get("start_col") or "A",
        "order_process_days": int(rows["order_process_days"]) if rows.get("order_process_days") else 4,
        "default_lead_days": int(rows["default_lead_days"]) if rows.get("default_lead_days") else 15,
        "order_buffer_high_days": int(rows["order_buffer_high_days"]) if rows.get("order_buffer_high_days") else 0,
        "order_buffer_medium_days": int(rows["order_buffer_medium_days"]) if rows.get("order_buffer_medium_days") else 2,
        "order_buffer_low_days": int(rows["order_buffer_low_days"]) if rows.get("order_buffer_low_days") else 4,
    }


def save_settings(data):
    """Upsert all settings in one transaction."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for key, value in data.items():
                cur.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                    """,
                    (key, value),
                )
        conn.commit()

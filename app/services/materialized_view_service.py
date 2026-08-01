"""Refreshes the app's materialized views.

The views themselves (mv_sales_fact, mv_product_supplier_lead_time) are
created by Alembic migrations, not here -- this module only issues REFRESH.
Both views have a unique index (see migrations) so REFRESH CONCURRENTLY can
be used, keeping the view queryable (with slightly stale data) while a
refresh is in progress instead of locking it.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MV_SALES_FACT = "mv_sales_fact"
MV_LEAD_TIME = "mv_product_supplier_lead_time"


def _refresh(session: Session, view_name: str, concurrently: bool = True) -> None:
    clause = "CONCURRENTLY " if concurrently else ""
    logger.info("Refreshing materialized view %s (concurrently=%s)", view_name, concurrently)
    try:
        session.execute(text(f"REFRESH MATERIALIZED VIEW {clause}{view_name}"))
        session.commit()
    except Exception:
        session.rollback()
        if concurrently:
            # Concurrent refresh requires a populated view + unique index;
            # fall back to a plain (blocking) refresh, e.g. on first run.
            logger.warning("Concurrent refresh of %s failed, retrying non-concurrently", view_name)
            session.execute(text(f"REFRESH MATERIALIZED VIEW {view_name}"))
            session.commit()
        else:
            raise


def refresh_sales_fact_view(session: Session) -> None:
    _refresh(session, MV_SALES_FACT)


def refresh_lead_time_view(session: Session) -> None:
    _refresh(session, MV_LEAD_TIME)

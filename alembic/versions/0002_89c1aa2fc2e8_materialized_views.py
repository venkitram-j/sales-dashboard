"""materialized views: mv_sales_fact, mv_product_supplier_lead_time

Revision ID: 89c1aa2fc2e8
Revises: 740d48caa004
Create Date: 2026-07-30 00:05:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "89c1aa2fc2e8"
down_revision: Union[str, None] = "740d48caa004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_sales_fact AS
        SELECT
            id,
            product_code,
            description,
            branch,
            sales_qty,
            pending_po,
            admin,
            buyer,
            source_file,
            period_start,
            period_end,
            created_at
        FROM sales_fact
        WITH NO DATA;
        """
    )
    # A unique index on id is required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    op.execute("CREATE UNIQUE INDEX ix_mv_sales_fact_id ON mv_sales_fact (id);")
    op.execute("CREATE INDEX ix_mv_sales_fact_product_code ON mv_sales_fact (product_code);")
    op.execute("CREATE INDEX ix_mv_sales_fact_branch ON mv_sales_fact (branch);")

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_product_supplier_lead_time AS
        SELECT
            id,
            product_code,
            buyer,
            lead_days,
            updated_at
        FROM product_supplier_lead_time
        WITH NO DATA;
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_mv_lead_time_id ON mv_product_supplier_lead_time (id);"
    )

    # Both views start empty (WITH NO DATA); populate them so the app's
    # first REFRESH ... CONCURRENTLY has a valid baseline to work from.
    op.execute("REFRESH MATERIALIZED VIEW mv_sales_fact;")
    op.execute("REFRESH MATERIALIZED VIEW mv_product_supplier_lead_time;")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_product_supplier_lead_time;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_sales_fact;")

"""initial schema: create all tables, materialized views, and indexes

Revision ID: 740d48caa004
Revises:
Create Date: 2026-07-30 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "740d48caa004"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CREATE_VIEW_SQL = """
    CREATE MATERIALIZED VIEW mv_sales_fact AS
    WITH time_buckets AS (
        SELECT 'ALL'::text AS time_range, NULL::date AS min_period_end
        UNION ALL
        SELECT 'LAST_7_DAYS', (CURRENT_DATE - INTERVAL '7 days')::date
        UNION ALL
        SELECT 'LAST_30_DAYS', (CURRENT_DATE - INTERVAL '30 days')::date
        UNION ALL
        SELECT 'LAST_90_DAYS', (CURRENT_DATE - INTERVAL '90 days')::date
    ),
    base AS (
        SELECT
            sf.id,
            sf.product_code,
            sf.description,
            sf.department,
            sf.branch,
            sf.sales_qty,
            sf.pending_po,
            sf.admin,
            sf.buyer,
            sf.source_file,
            sf.period_start,
            sf.period_end,
            sf.created_at,
            tb.time_range
        FROM sales_fact sf
        CROSS JOIN time_buckets tb
        WHERE tb.min_period_end IS NULL OR sf.period_end >= tb.min_period_end
    ),
    windowed AS (
        SELECT
            b.*,
            COALESCE(SUM(b.sales_qty) OVER w, 0) AS total_sales_qty,
            COALESCE(SUM(b.pending_po) OVER w, 0) AS total_pending_po,
            MIN(b.period_start) OVER w AS branch_product_period_start,
            MAX(b.period_end) OVER w AS branch_product_period_end
        FROM base b
        WINDOW w AS (PARTITION BY b.time_range, b.branch, b.product_code)
    ),
    settings AS (
        SELECT
            COALESCE(MAX(value) FILTER (WHERE key = 'order_process_days'), '0')::int AS order_process_days,
            COALESCE(MAX(value) FILTER (WHERE key = 'default_lead_days'), '0')::int AS default_lead_days,
            COALESCE(MAX(value) FILTER (WHERE key = 'order_buffer_high_days'), '0')::int AS order_buffer_high_days,
            COALESCE(MAX(value) FILTER (WHERE key = 'order_buffer_medium_days'), '0')::int AS order_buffer_medium_days,
            COALESCE(MAX(value) FILTER (WHERE key = 'order_buffer_low_days'), '0')::int AS order_buffer_low_days
        FROM app_settings
    ),
    enriched AS (
        SELECT
            w.*,
            (w.total_sales_qty
                / GREATEST(w.branch_product_period_end - w.branch_product_period_start + 1, 1)
            ) AS average_daily_sales,
            COALESCE(lt.lead_days, s.default_lead_days, 0) AS effective_lead_days,
            s.order_process_days,
            s.order_buffer_high_days,
            s.order_buffer_medium_days,
            s.order_buffer_low_days
        FROM windowed w
        CROSS JOIN settings s
        LEFT JOIN product_supplier_lead_time lt
            ON lt.product_code = w.product_code AND lt.buyer = w.buyer
    ),
    -- priority thresholds mirror app.services.reorder_logic.classify_priority
    prioritized AS (
        SELECT
            e.*,
            CASE
                WHEN e.average_daily_sales >= 1000 THEN 'HIGH'
                WHEN e.average_daily_sales >= 500 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS priority
        FROM enriched e
    ),
    scored AS (
        SELECT
            p.*,
            CASE p.priority
                WHEN 'HIGH' THEN p.order_buffer_high_days
                WHEN 'MEDIUM' THEN p.order_buffer_medium_days
                ELSE p.order_buffer_low_days
            END AS order_buffer_days,
            CASE
                WHEN p.average_daily_sales > 0
                THEN p.branch_product_period_end
                    + CEIL(p.total_pending_po / p.average_daily_sales)::int
                ELSE NULL
            END AS stock_lasts_until
        FROM prioritized p
    ),
    reorder_dates AS (
        SELECT
            s.*,
            (s.branch_product_period_end
                + (s.order_process_days - s.effective_lead_days + s.order_buffer_days)
            ) AS reorder_date
        FROM scored s
    )
    -- reorder_status ladder mirrors app.services.reorder_logic.classify_reorder_status
    SELECT
        r.id,
        r.product_code,
        r.description,
        r.department,
        r.branch,
        r.sales_qty,
        r.pending_po,
        r.admin,
        r.buyer,
        r.source_file,
        r.period_start,
        r.period_end,
        r.created_at,
        r.time_range,
        r.total_sales_qty,
        r.total_pending_po,
        r.branch_product_period_start,
        r.branch_product_period_end,
        r.average_daily_sales,
        r.priority,
        r.stock_lasts_until,
        r.reorder_date,
        CASE
            WHEN r.reorder_date <= CURRENT_DATE THEN
                CASE r.priority
                    WHEN 'HIGH' THEN 'OVERDUE'
                    WHEN 'MEDIUM' THEN 'REORDER'
                    ELSE 'PLAN'
                END
            WHEN r.reorder_date <= CURRENT_DATE + 2 THEN
                CASE r.priority
                    WHEN 'HIGH' THEN 'REORDER'
                    WHEN 'MEDIUM' THEN 'PLAN'
                    ELSE 'OK'
                END
            WHEN r.reorder_date <= CURRENT_DATE + 4 THEN
                CASE r.priority
                    WHEN 'HIGH' THEN 'PLAN'
                    ELSE 'OK'
                END
            ELSE 'OK'
        END AS reorder_status
    FROM reorder_dates r
    WITH NO DATA;
    """


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(length=20), nullable=False, server_default="string"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("key", name="uq_app_settings_key"),
    )
    op.create_index("ix_app_settings_key", "app_settings", ["key"])

    op.create_table(
        "ingested_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_path", sa.String(length=2000), nullable=False),
        sa.Column("file_mtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("file_name", name="uq_ingested_files_file_name"),
    )
    op.create_index("ix_ingested_files_file_name", "ingested_files", ["file_name"])

    op.create_table(
        "sales_fact",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("product_code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=False),
        sa.Column("branch", sa.String(length=100), nullable=False),
        sa.Column("sales_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("pending_po", sa.Numeric(18, 4), nullable=True),
        sa.Column("admin", sa.String(length=200), nullable=True),
        sa.Column("buyer", sa.String(length=200), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_file"], ["ingested_files.file_name"], ondelete="CASCADE",
            name="fk_sales_fact_source_file",
        ),
    )
    op.create_index("ix_sales_fact_product_code", "sales_fact", ["product_code"])
    op.create_index("ix_sales_fact_branch", "sales_fact", ["branch"])
    op.create_index("ix_sales_fact_description", "sales_fact", ["description"])
    op.create_index("ix_sales_fact_department", "sales_fact", ["department"])
    op.create_index("ix_sales_fact_admin", "sales_fact", ["admin"])
    op.create_index("ix_sales_fact_product_branch", "sales_fact", ["product_code", "branch"])

    op.create_table(
        "product_supplier_lead_time",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_code", sa.String(length=100), nullable=False),
        sa.Column("buyer", sa.String(length=200), nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("product_code", "buyer", name="uq_product_supplier"),
    )

    op.execute(_CREATE_VIEW_SQL)

    # (time_range, id) instead of plain (id): each sales_fact row now
    # appears up to once per bucket it falls into, so id alone is no
    # longer unique.
    op.execute(
        "CREATE UNIQUE INDEX ix_mv_sales_fact_time_range_id ON mv_sales_fact (time_range, id);"
    )
    op.execute("CREATE INDEX ix_mv_sales_fact_time_range ON mv_sales_fact (time_range);")
    op.execute("CREATE INDEX ix_mv_sales_fact_product_code ON mv_sales_fact (product_code);")
    op.execute("CREATE INDEX ix_mv_sales_fact_branch ON mv_sales_fact (branch);")
    op.execute(
        "CREATE INDEX ix_mv_sales_fact_bucket_branch_product "
        "ON mv_sales_fact (time_range, branch, product_code);"
    )

    op.execute("REFRESH MATERIALIZED VIEW mv_sales_fact;")

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
    op.drop_table("product_supplier_lead_time")
    op.drop_index("ix_sales_fact_product_branch", table_name="sales_fact")
    op.drop_index("ix_sales_fact_source_file", table_name="sales_fact")
    op.drop_index("ix_sales_fact_branch", table_name="sales_fact")
    op.drop_index("ix_sales_fact_product_code", table_name="sales_fact")
    op.drop_table("sales_fact")
    op.drop_index("ix_ingested_files_file_name", table_name="ingested_files")
    op.drop_table("ingested_files")
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.drop_table("app_settings")

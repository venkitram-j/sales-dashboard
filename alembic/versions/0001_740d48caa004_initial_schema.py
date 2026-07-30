"""initial schema: app_settings, ingested_files, sales_fact, product_supplier_lead_time

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
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
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
    op.create_index("ix_sales_fact_source_file", "sales_fact", ["source_file"])
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


def downgrade() -> None:
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

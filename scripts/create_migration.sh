#!/usr/bin/env bash
# Autogenerates a new migration by diffing the ORM models against the DB.
# Usage: ./scripts/create_migration.sh "add new column to sales_fact"
# NOTE: autogenerate cannot see materialized views (they aren't ORM models),
# so any changes to mv_sales_fact / mv_product_supplier_lead_time must be
# hand-written (see alembic/versions/0002_..._materialized_views.py for a
# template) using op.execute("CREATE/DROP/ALTER MATERIALIZED VIEW ...").
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-development}"

if [ -z "${1:-}" ]; then
  echo "Usage: $0 \"migration message\"" >&2
  exit 1
fi

alembic revision --autogenerate -m "$1"
echo "Review the generated file in alembic/versions/ before applying it."

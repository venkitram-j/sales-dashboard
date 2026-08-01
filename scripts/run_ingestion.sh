#!/usr/bin/env bash
# Runs data ingestion (parse + bulk-load new/modified Excel files from
# source_folder, then refresh mv_sales_fact) without starting the Streamlit
# app. Suitable for cron/systemd timers, e.g.:
#
#   # Every 15 minutes:
#   */15 * * * * APP_ENV=production /path/to/inventory_app/scripts/run_ingestion.sh production >> /var/log/inventory-ingest.log 2>&1
#
# Usage: ./scripts/run_ingestion.sh [APP_ENV]   (defaults to development)
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${1:-development}"

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

exec python scripts/run_ingestion.py

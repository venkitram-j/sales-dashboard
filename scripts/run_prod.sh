#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV=production
alembic upgrade head
exec streamlit run main.py \
  --server.headless=true \
  --server.runOnSave=false \
  --browser.gatherUsageStats=false

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV=development
exec streamlit run main.py --server.runOnSave=true

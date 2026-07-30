#!/usr/bin/env bash
# Applies all pending migrations. Usage: ./scripts/migrate.sh [APP_ENV]
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${1:-development}"
alembic upgrade head

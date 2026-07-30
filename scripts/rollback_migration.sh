#!/usr/bin/env bash
# Rolls back the most recent migration. Usage: ./scripts/rollback_migration.sh [steps]
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-development}"
STEPS="${1:-1}"
alembic downgrade "-${STEPS}"

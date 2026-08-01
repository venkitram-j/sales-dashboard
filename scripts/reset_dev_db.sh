#!/usr/bin/env bash
# DEV ONLY. Drops every table/view managed by this app and re-applies all
# migrations from scratch. Refuses to run unless APP_ENV=development.
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="development"

read -r -p "This will DROP ALL DATA in the development database. Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

alembic downgrade base
alembic upgrade head
echo "Development database reset complete."

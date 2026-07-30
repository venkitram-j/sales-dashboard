#!/usr/bin/env bash
# One-time (or repeatable) development environment bootstrap.
# - creates a virtualenv
# - installs dependencies
# - copies .env.example -> .env if missing
# - runs migrations
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements-dev.txt

if [ ! -f ".env" ]; then
  echo "Creating .env from .env.example (edit it with your real DB credentials)..."
  cp .env.example .env
fi

export APP_ENV=development
echo "Running migrations..."
alembic upgrade head

echo "Dev environment ready. Activate it with: source .venv/bin/activate"
echo "Then start the app with: ./scripts/run_dev.sh"

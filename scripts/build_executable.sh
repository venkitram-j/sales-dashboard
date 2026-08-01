#!/usr/bin/env bash
# Builds a standalone executable of the app using PyInstaller.
# See the README's "Standalone executable (PyInstaller)" section for the
# full explanation and caveats. Usage:
#   ./scripts/build_executable.sh [--onedir]
#
# Default is --onefile (single binary, slower to start -- extracts to a
# temp dir every run). Pass --onedir for a folder build instead (faster
# startup, easier to debug missing-file errors, more files to distribute).
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="--onefile"
if [ "${1:-}" = "--onedir" ]; then
  MODE="--onedir"
fi

if [ ! -d ".venv" ]; then
  echo "No .venv found -- run ./scripts/setup_dev.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements-build.txt

pyinstaller \
  --name InventoryApp \
  "$MODE" \
  --noconfirm \
  --clean \
  --add-data "main.py:." \
  --collect-all streamlit \
  --collect-all altair \
  --collect-all pyarrow \
  --hidden-import streamlit.runtime.scriptrunner.magic_funcs \
  desktop_launcher.py

echo
echo "Build complete: dist/InventoryApp"
echo "Copy .env.example to dist/InventoryApp/.env (or .env.production) and fill"
echo "in real DB credentials before running the executable -- see the README."

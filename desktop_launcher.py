"""Entry point used to build a standalone executable with PyInstaller.

Not used when running the app normally (`streamlit run main.py` /
scripts/run_dev.sh / scripts/run_prod.sh) -- this exists solely so
PyInstaller has a plain Python script to freeze. See the "Standalone
executable (PyInstaller)" section in the README for the full build
instructions and important caveats (the frozen app is a UI process only;
it still needs network access to an already-migrated PostgreSQL database,
and its .env/.env.production must sit next to the built executable).

Why this file exists instead of freezing main.py directly: Streamlit's
`streamlit run <path>` reads and executes that path as a *script file* at
runtime, not as an imported module -- so PyInstaller's static import
analysis (which only follows `import` statements) would never discover
main.py or anything it imports. This launcher solves that by (a) eagerly
importing the app package so PyInstaller's analyzer bundles every
transitive dependency, and (b) resolving main.py's on-disk path correctly
whether running from source or from a frozen bundle, then handing that
path to Streamlit's own CLI to run exactly as `streamlit run main.py` would.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Force PyInstaller's static analyzer to see (and therefore bundle) the
# app package and everything it transitively imports -- main.py itself is
# never `import`-ed (see module docstring), so without this, dependencies
# only reachable through main.py would be silently left out of the build.
import app.config  # noqa: F401
import app.database  # noqa: F401
import app.models  # noqa: F401
import app.services.dashboard_service  # noqa: F401
import app.services.file_parser_service  # noqa: F401
import app.services.ingestion_service  # noqa: F401
import app.services.lead_time_service  # noqa: F401
import app.services.materialized_view_service  # noqa: F401
import app.services.settings_service  # noqa: F401
import app.utils.logging_config  # noqa: F401
import app.utils.ui  # noqa: F401
import app.views.dashboard_view  # noqa: F401
import app.views.lead_time_view  # noqa: F401
import app.views.settings_view  # noqa: F401


def _resource_path(relative: str) -> Path:
    """Resolves `relative` against the running app's actual location,
    whether that's this source tree or a PyInstaller-extracted bundle
    (sys._MEIPASS, set in both --onefile and --onedir builds)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def main() -> None:
    from streamlit.web import cli as stcli

    main_script = _resource_path("main.py")
    if not main_script.exists():
        raise FileNotFoundError(
            f"main.py not found at {main_script}. If this is a frozen build, make "
            "sure it was built with --add-data to include main.py (see the README's "
            "'Standalone executable' section)."
        )

    sys.argv = [
        "streamlit",
        "run",
        str(main_script),
        "--global.developmentMode=false",
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()

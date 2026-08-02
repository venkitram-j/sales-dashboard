# Inventory & Supply Chain App

A Streamlit application for ingesting branch sales/inventory data from Excel
files into PostgreSQL, browsing it on a dashboard, and managing
product-supplier lead times used for order/reorder planning.

## Contents

- [Architecture](#architecture)
- [Data model](#data-model)
- [Features](#features)
- [mv_sales_fact: time-range buckets & reorder planning](#mv_sales_fact-time-range-buckets--reorder-planning)
- [File naming convention (required)](#file-naming-convention-required)
- [Getting started (development)](#getting-started-development)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [Standalone ingestion](#standalone-ingestion)
- [Scripts](#scripts)
- [Production deployment](#production-deployment)
- [Standalone executable (PyInstaller)](#standalone-executable-pyinstaller)
- [Testing](#testing)
- [Project layout](#project-layout)

## Architecture

- **UI**: Streamlit, using `st.navigation`/`st.Page` for multipage routing
  and class-based views (`app/views/`) — each page is a class with a
  `render()` method (via a shared `BaseView` ABC) rather than a top-to-bottom
  script, so pages share a consistent lifecycle and error boundary.
- **Database**: PostgreSQL. Postgres is a hard requirement — the app relies
  on native `MATERIALIZED VIEW` support (`mv_sales_fact`,
  `mv_product_supplier_lead_time`) and `COPY` for bulk loading.
- **ORM / migrations**: SQLAlchemy 2.0 (typed `Mapped[...]` models) +
  Alembic. Tables are managed by Alembic migrations; the two materialized
  views are also created/refreshed via migrations and a small service module
  (materialized views aren't ORM models, so autogenerate can't see them —
  see [Database migrations](#database-migrations)).
  scale to millions of rows without saturating executemany()/INSERT
  round-trips.
- **Config**: `pydantic-settings`, loaded from `.env` (development) or
  `.env.production` (production), selected via the `APP_ENV` environment
  variable. Real environment variables always override `.env` file values,
  which is how secrets should be supplied in production.
- **Logging**: stdlib `logging`, configured once in
  `app/utils/logging_config.py` — console + rotating file handler under
  `LOG_DIR`, optionally JSON-formatted (`LOG_JSON=true`) for log aggregators.

## Data model

| Table | Purpose |
|---|---|
| `app_settings` | Key/value store for app configuration (see below) |
| `ingested_files` | One row per **successfully** ingested Excel file (mtime, size, row count). A failed ingest never leaves a row — see Dashboard below |
| `sales_fact` | One row per product/branch record parsed from a source file |
| `product_supplier_lead_time` | Lead time (days) per product_code/buyer mapping |
| `mv_sales_fact` (materialized view) | Time-range-bucketed, branch/product-aggregated reorder-planning view built from `sales_fact` — see [mv_sales_fact: time-range buckets & reorder planning](#mv_sales_fact-time-range-buckets--reorder-planning) |
| `mv_product_supplier_lead_time` (materialized view) | Read-optimized copy of `product_supplier_lead_time`, refreshed after uploads/updates |

**Why `app_settings` is key/value, not one column per setting:** the spec
asks for a table that "accommodates easy addition of settings in the
future." Modeling it as `key -> value` (with a `value_type` tag for casting)
means adding a new setting is a one-line addition to the
`SETTING_DEFINITIONS` registry in `app/services/settings_service.py` —
no schema migration required, only a data bootstrap (which happens
automatically on every app start via `SettingsService.bootstrap_defaults()`).

Current settings: `source_folder`, `header_row`, `start_col`,
`order_process_days`, `default_lead_days`, `order_buffer_high_days`,
`order_buffer_medium_days`, `order_buffer_low_days`.

## Features

### 1. Settings
- On first run (no `source_folder` configured yet), a full-page form is
  shown and **nothing else in the app loads** until it's submitted
  successfully.
- After that, the same fields are available as a form in the sidebar at all
  times.
- Saving the sidebar form triggers one of two things:
  - If `source_folder` changed: all `sales_fact` and `ingested_files` data
    is wiped, every *other* setting is reset to its default, and a full
    re-ingest of the new folder runs immediately.
  - Otherwise: only `mv_sales_fact` is refreshed (cheap).
- Validation runs across **every** field in the submitted form before
  anything is saved (`SettingsService.update`, which raises a single
  `SettingsValidationError`). If one or more required fields are missing or
  invalid, the error names all of them by their on-screen label — e.g.
  *"Missing or invalid value for: Source Folder"* — rather than the form
  silently rejecting one field at a time. This applies identically to the
  initial full-page form and the sidebar form.

### 2. Dashboard
- **Empty state**: if `mv_sales_fact` has no rows yet (nothing ingested,
  or everything failed), the page shows *only* a **Refresh** button and a
  message asking you to check that your Excel file names follow the
  required naming convention and that **Source Folder** in Settings points
  at the right directory — no filters or empty table are shown over
  nonexistent data.
- Before this page is usable the first time, all eligible Excel files in
  `source_folder` are parsed and bulk-loaded into `sales_fact`.
- A **Refresh** button re-scans `source_folder` for new or modified files
  (detected via on-disk modification time vs. the recorded `file_mtime` in
  `ingested_files`), re-ingests only what changed, and refreshes
  `mv_sales_fact`.
  - New file → parsed and inserted.
  - Modified file (same name, newer mtime) → existing rows for that
    `source_file` are deleted first, then the file is re-parsed and
    re-inserted.
  - Unchanged file → skipped entirely.
  - A file that fails to parse or load (bad naming convention, missing
    columns, DB error, etc.) is reported by name with its error, and —
    critically — **never leaves a partial `ingested_files` row behind**: if
    ingestion fails at any point after that row was created, it's deleted
    again in the same operation (`IngestionService.ingest_file`), so
    `ingested_files` always accurately reflects what's actually in
    `sales_fact`. This also matters for a subtler reason: `sales_fact.source_file`
    has a foreign key to `ingested_files.file_name`, and the bulk load runs
    on its own database connection (a raw `COPY`, separate from the regular
    session) — so the `ingested_files` row for a file must be committed
    *before* that file's rows are `COPY`-ed in, or the `COPY` fails with a
    `ForeignKeyViolation`. `ingest_file()` commits the `ingested_files`
    upsert first and only then runs the bulk copy, cleaning up if the copy
    fails.
- Filters (`product_code`, `branch` multiselects) and a free-text search
  (matches `product_code`, `branch`, `description`, `admin`, `buyer`) all
  query `mv_sales_fact`, never `sales_fact` directly.
- A **Time Range** selector (All / Last 7 Days / Last 30 Days / Last 90
  Days) controls which pre-computed bucket of `mv_sales_fact` is queried —
  see [mv_sales_fact: time-range buckets & reorder planning](#mv_sales_fact-time-range-buckets--reorder-planning)
  below for how that's built.
- The grid shows one row per **branch + product_code** (not one row per
  ingested file) with reorder-planning columns: total sales quantity,
  total pending PO, the actual period the aggregate covers, average daily
  sales, a priority tier, a projected stock-out date, a reorder date, and
  a reorder status — see the same section below.

### 3. Product-Supplier Lead Time
- An editable grid (`st.data_editor`) at the top of the page lets you update
  `lead_days` for existing product/buyer mappings; **Save Changes** persists
  edits and refreshes `mv_product_supplier_lead_time`.
- Below that, uploading an Excel file (columns: `Product Code`, `Buyer`,
  `Lead Days`) **replaces the entire table** — all existing rows are
  deleted and the uploaded rows are inserted — then the materialized view is
  refreshed. Missing/blank `Lead Days` values fall back to
  `app_settings.default_lead_days`.

## mv_sales_fact: time-range buckets & reorder planning

`mv_sales_fact` isn't a plain 1:1 copy of `sales_fact` anymore
(`alembic/versions/0004_866544bf9f76_mv_sales_fact_reorder_columns.py`
rebuilds it — Postgres has no `ALTER MATERIALIZED VIEW` for this kind of
change, so the migration drops and recreates it). It now carries:

- **A `time_range` bucket dimension**: `'ALL'`, `'LAST_7_DAYS'`,
  `'LAST_30_DAYS'`, `'LAST_90_DAYS'`. Each `sales_fact` row appears once
  per bucket it falls into (by `period_end >= CURRENT_DATE - N`), so the
  Dashboard's Time Range selector is a plain `WHERE time_range = ...`
  against pre-aggregated data — the filtering lives in the view itself,
  not in a query-time aggregation. This trades view size (up to ~4x
  `sales_fact`'s row count) for query-time simplicity and speed.
- **Per (time_range, branch, product_code) window-function columns**,
  identical across every row in the same group:
  - `total_sales_qty`, `total_pending_po` — `SUM(...)` across every
    `sales_fact` row in that group.
  - `branch_product_period_start` / `branch_product_period_end` — the
    actual `MIN(period_start)`/`MAX(period_end)` across the group; i.e.
    the real date span the aggregate covers, which can be narrower than
    the nominal window (e.g. "Last 30 Days" might only actually have 12
    days of ingested data in it).
  - `average_daily_sales` = `total_sales_qty / (branch_product_period_end
    - branch_product_period_start + 1)`.
  - `priority` = `HIGH` if `average_daily_sales >= 1000`, `MEDIUM` if
    `>= 500`, else `LOW`.
  - `stock_lasts_until` = `branch_product_period_end +
    CEIL(total_pending_po / average_daily_sales)` (`NULL` if there's no
    sales velocity to project from).
  - `reorder_date` = `branch_product_period_end + (order_process_days -
    effective_lead_days + order_buffer_days_for_priority)`, where
    `effective_lead_days` is the product's lead time from
    `product_supplier_lead_time` (matched on product_code **and** the
    group's buyer) falling back to `app_settings.default_lead_days` if
    there's no match, and the buffer is whichever of
    `order_buffer_high_days` / `_medium_days` / `_low_days` matches the
    row's `priority`.
  - `reorder_status`: `OVERDUE`/`REORDER`/`PLAN` if `reorder_date <=`
    today, escalating down through `REORDER`/`PLAN`/`OK` by priority at
    `today+2` and `today+4`, `OK` beyond that — see
    `app.services.reorder_logic.classify_reorder_status` for the exact
    ladder (kept as plain, unit-tested Python specifically so the SQL
    `CASE` expression it mirrors has a readable, testable reference).

The Dashboard's `DashboardService.query()` reads this with `SELECT
DISTINCT ON (branch, product_code) ... ORDER BY ... period_end DESC`, so
what you see is one summary row per branch/product for the selected time
range (picking the most recently reported period as the representative
row when several `sales_fact` rows landed in the same group), not one row
per ingested file.

**Because `reorder_date`/`priority`/etc. depend on `app_settings` and
`product_supplier_lead_time`, not just `sales_fact`**, `mv_sales_fact`
needs refreshing whenever either changes — not only after ingestion. This
is already wired up: saving order/buffer/lead-time settings in the
sidebar refreshes it (`main.py`'s `_handle_pending_settings_change`), and
so does any change to lead times on the Product-Supplier Lead Time page
(`LeadTimeService.replace_all`/`update_row`/`update_many`).

### Assumptions worth knowing about

The requirements for a few of these columns left room for interpretation;
here's exactly what was assumed, so it's easy to spot and correct if it
doesn't match what you actually meant:

- **`total_pending_po` is a `SUM`** across whatever rows fall in the
  bucket, not a latest/point-in-time value. Pending PO is normally a
  snapshot quantity (how much is currently on order), so summing it
  across multiple overlapping reporting periods can overstate it — but
  "total pending PO" is literally what was asked for. If a snapshot
  (latest by `period_end`) is what's actually wanted, that's a one-line
  change in the migration (a `DISTINCT ON`/`FILTER` style pick instead of
  `SUM`).
- **"Stock lasts until" needs a *remaining stock* quantity**, and this
  schema has no on-hand-inventory column — only `sales_qty` (outflow) and
  `pending_po` (on order). `total_pending_po` is used as the "remaining
  stock" proxy. If there's a real stock-on-hand source, that should
  replace it in the migration's `stock_lasts_until` expression.
- **`reorder_date` is anchored to `branch_product_period_end`** (the
  branch/product's own "as of" date within the selected bucket), not to
  `stock_lasts_until`. Anchoring to `stock_lasts_until` instead would give
  every zero-sales-velocity row a `NULL` reorder date/status, which seemed
  wrong — a never-sold item still needs a reorder decision. Flag it if a
  stock-depletion-anchored date was actually intended.
- The "difference between order process days and product lead time"
  wording was read as `order_process_days - effective_lead_days` (in that
  order), added to `branch_product_period_end` along with the priority's
  buffer days. Since lead time is normally the larger of the two, this
  nets out to *subtracting* roughly `(lead_time - order_process_days)`
  days from the period end before adding the buffer — i.e., longer lead
  times push the reorder date earlier, which is the intended direction,
  but the exact sign/formula was inferred from a genuinely ambiguous
  sentence. Double-check `reorder_date` values against a known case (see
  the worked example below) if this matters for real ordering decisions.
- `reorder_date`/`reorder_status`/`stock_lasts_until` are computed
  relative to `CURRENT_DATE` **at refresh time**, so they go stale between
  refreshes exactly like the rest of the view. Schedule
  `scripts/run_ingestion.sh` (or open the Dashboard) at least daily if
  these need to stay current without manual refreshes.

### Worked example (verified against a real PostgreSQL instance)

With `order_process_days=3`, `default_lead_days=5`,
`order_buffer_high_days=4`, `order_buffer_medium_days=2`, a product with
`lead_days=7`, 13,000 total units sold and 2,500 total pending PO over a
20-day actual window ending `2026-07-31`:

- `average_daily_sales` = 13000 / 20 = **650** → `priority` = **MEDIUM**
  (≥ 500, < 1000)
- `stock_lasts_until` = 2026-07-31 + CEIL(2500 / 650) = 2026-07-31 + 4 =
  **2026-08-04**
- `reorder_date` = 2026-07-31 + (3 − 7 + 2) = 2026-07-31 − 2 =
  **2026-07-29**
- With "today" = 2026-08-01, `reorder_date <= today` → priority MEDIUM →
  `reorder_status` = **REORDER**

## File naming convention (required)

Every source Excel file **must** encode its reporting period in its file
name as two dates, `period_start` then `period_end`, in one of these forms:

```
<anything>_YYYYMMDD_YYYYMMDD.xlsx
<anything>_YYYY-MM-DD_YYYY-MM-DD.xlsx
```

Examples:

```
Sales_20260101_20260131.xlsx
Branch12-Sales_2026-01-01_2026-01-31.xlsx
Sales_20260201_20260228_v2.xlsx        # trailing suffix after the 2nd date is fine
```

A file whose name doesn't contain a valid, correctly-ordered date pair is
rejected with an actionable error message (visible on the Dashboard after a
refresh) and is **not** ingested; fix the file name and refresh again.

Each source file's data (`Product Code`, `Description`, `Branch`,
`Sales Qty`, `Pending PO`, `Admin`, `Buyer`) must start at the Excel column
configured as `start_col` in Settings, with headers on the row configured as
`header_row`.

## Getting started (development)

Prerequisites: Python 3.11+, a running PostgreSQL instance you can create a
database in.

```bash
git clone <this-repo>
cd inventory_app

# Create the dev database (adjust to your local Postgres setup)
createdb inventory_dev

# One-shot bootstrap: venv, dependencies, .env, migrations
./scripts/setup_dev.sh

# Edit .env with your real DB credentials, then verify connectivity
source .venv/bin/activate
python scripts/check_db_connection.py

# Run the app
./scripts/run_dev.sh
```

The app opens in your browser (default `http://localhost:8501`). Since
this is the first run, you'll see the initial setup form — point
`source_folder` at a directory containing correctly-named `.xlsx` files
(see naming convention above) and submit.

## Configuration

Copy `.env.example` to `.env` (development) or `.env.production`
(production) and fill in real values. `APP_ENV` selects which file is
loaded; actual environment variables always take precedence over file
contents.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` or `production` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE` | PostgreSQL connection |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` | SQLAlchemy connection pool |
| `LOG_LEVEL`, `LOG_DIR`, `LOG_JSON` | Logging |
| `INGEST_BATCH_SIZE` | Reserved for chunked ingestion tuning |
| `INGEST_FILE_EXTENSIONS` | Comma-separated extensions scanned in `source_folder` (default `.xlsx,.xlsm`) |

## Database migrations

Migrations are managed with Alembic and target whatever database `APP_ENV`
currently points at (`alembic/env.py` builds the connection URL from
`app.config.get_settings()`, so there's nothing to keep in sync in
`alembic.ini` itself).

```bash
./scripts/migrate.sh                 # apply all pending migrations (dev)
./scripts/migrate.sh production      # apply against production config
./scripts/create_migration.sh "add new column to sales_fact"
./scripts/rollback_migration.sh      # roll back one migration
./scripts/rollback_migration.sh 2    # roll back two migrations
```

**Materialized views are not ORM models**, so `alembic revision
--autogenerate` cannot detect changes to `mv_sales_fact` or
`mv_product_supplier_lead_time`. Any change to those views must be a
hand-written migration using `op.execute("CREATE/DROP/ALTER MATERIALIZED
VIEW ...")` — see `alembic/versions/0002_..._materialized_views.py` as a
template. Both views are created with a unique index on `id` so the app can
use `REFRESH MATERIALIZED VIEW CONCURRENTLY` (keeps the view queryable
during a refresh); the refresh service transparently falls back to a
blocking refresh if the concurrent refresh isn't possible yet (e.g. an empty
view on first run).

## Standalone ingestion

Data ingestion (the same parse-and-bulk-load pipeline the Dashboard's
**Refresh** button runs) can be run independently of the Streamlit app —
useful for keeping the data fresh on a schedule even when nobody has the
app open:

```bash
./scripts/run_ingestion.sh production
# or directly:
APP_ENV=production python scripts/run_ingestion.py
```

It scans `source_folder`, ingests whatever's new or modified, refreshes
`mv_sales_fact`, prints a summary, and exits non-zero if `source_folder`
isn't configured yet or if any file failed. Example cron entry to run it
every 15 minutes:

```cron
*/15 * * * * cd /path/to/inventory_app && ./scripts/run_ingestion.sh production >> /var/log/inventory-ingest.log 2>&1
```

## Scripts

All scripts live in `scripts/` and are safe to run from any working
directory (they `cd` to the project root themselves).

| Script | Purpose |
|---|---|
| `setup_dev.sh` | venv + install + `.env` bootstrap + migrate |
| `run_dev.sh` | Run the app in development mode (auto-reload on save) |
| `run_prod.sh` | Migrate then run the app in production mode (headless) |
| `migrate.sh [env]` | Apply pending migrations |
| `create_migration.sh "<message>"` | Autogenerate a new migration from model changes |
| `rollback_migration.sh [steps]` | Roll back the N most recent migrations (default 1) |
| `reset_dev_db.sh` | **Dev only.** Drops and recreates the whole schema |
| `check_db_connection.py` | Verifies the configured DB is reachable |
| `run_ingestion.sh` / `run_ingestion.py` | Run data ingestion standalone (no Streamlit app needed) — for cron/systemd timers |

## Production deployment

1. Provision PostgreSQL and a dedicated app database/user.
2. Create `.env.production` (never commit it) with real credentials, using
   `.env.example` as the template.
3. `APP_ENV=production ./scripts/run_prod.sh` — this applies migrations
   first, then starts Streamlit headless with usage stats disabled.
4. Put a reverse proxy (nginx, ALB, etc.) with TLS in front of Streamlit's
   port; Streamlit itself does not terminate TLS.
5. Point `source_folder` at a path reachable by the process (a mounted
   network share, an synced object-storage folder, etc.).

## Standalone executable (PyInstaller)

You can package the app as a single executable with
[PyInstaller](https://pyinstaller.org/) — useful for handing the app to
someone who shouldn't need to install Python, pip, or any dependencies
themselves.

**What this does and doesn't give you.** The executable bundles the Python
interpreter, the app's code, and all of its dependencies (Streamlit,
SQLAlchemy, pandas, etc.) into one file that, when run, starts the same
Streamlit UI and opens it in the browser. It does **not** bundle
PostgreSQL — the machine running the executable still needs network access
to a PostgreSQL instance with the schema already migrated (`alembic upgrade
head`, run normally from a source checkout before you ever build or ship
the executable — the frozen executable is a UI process only, not a
migration tool).

### 1. Install the build dependencies

```bash
source .venv/bin/activate
pip install -r requirements-build.txt
```

### 2. Build it

The one-line way:

```bash
./scripts/build_executable.sh          # --onefile (single binary)
./scripts/build_executable.sh --onedir # a folder instead (see notes below)
```

...or run PyInstaller directly, which is what that script wraps:

```bash
pyinstaller \
  --name InventoryApp \
  --onefile \
  --noconfirm \
  --clean \
  --add-data "main.py:." \
  --collect-all streamlit \
  --collect-all altair \
  --collect-all pyarrow \
  --hidden-import streamlit.runtime.scriptrunner.magic_funcs \
  desktop_launcher.py
```

**On Windows**, PowerShell/cmd use `;` instead of `:` as the `--add-data`
separator: `--add-data "main.py;."`. Everything else is identical (run it
from an activated venv with `requirements-build.txt` installed).

Why `desktop_launcher.py` and not `main.py` directly: Streamlit's
`streamlit run <path>` reads and executes that path as a script file at
runtime, not as an `import`. PyInstaller's static analyzer only discovers
dependencies by following `import` statements, so freezing `main.py`
directly would silently leave out everything the app imports.
`desktop_launcher.py` (at the project root) works around this: it eagerly
imports the whole `app` package so PyInstaller's analyzer bundles every
transitive dependency, resolves `main.py`'s on-disk path correctly whether
running from source or from the frozen bundle, and then hands that path to
Streamlit's own CLI — equivalent to running `streamlit run main.py`. The
`--add-data "main.py:."` flag is what makes the raw `main.py` file
available on disk inside the bundle for that to work; `--collect-all
streamlit` (and `altair`/`pyarrow`, two of Streamlit's own dependencies)
pulls in the non-Python static assets (frontend JS/CSS, etc.) that
PyInstaller's import-following alone wouldn't find.

### 3. Configure and run the build

The build lands in `dist/InventoryApp` (a single file for `--onefile`, a
folder for `--onedir`). Before running it:

1. Copy `.env.example` to `.env` (or `.env.production`, matching
   `APP_ENV`) **in that same `dist/InventoryApp` folder** — i.e. next to
   the executable, not inside your source checkout. `app/config/settings.py`
   resolves this path relative to the running executable itself
   (`sys.executable`'s directory) specifically so it's editable after the
   build without rebuilding.
2. Run the executable (double-click on Windows/macOS, or `./InventoryApp`
   on Linux). It starts Streamlit and opens your default browser to it,
   the same as `streamlit run main.py` would.

### Notes and caveats

- **`--onefile` vs `--onedir`**: `--onefile` produces one binary that
  self-extracts to a temp directory on every launch — slower to start (a
  few seconds), but simplest to distribute. `--onedir` produces a folder
  (executable + a `_internal`/support directory) that runs faster since
  there's no extraction step, at the cost of shipping a folder instead of
  a single file. Prefer `--onedir` while troubleshooting a build — it's
  much easier to inspect for missing files.
- **Binary size**: expect 200–400+ MB. Streamlit alone pulls in a fair
  amount (its frontend assets, pyarrow, altair, etc.); this is normal for
  PyInstaller + Streamlit and not something specific to this app.
- **Antivirus false positives**: PyInstaller onefile binaries are
  sometimes flagged by Windows Defender/AV software (self-extracting +
  unsigned executables are a common heuristic trigger). Code-signing the
  binary (out of scope here) resolves this for real distribution.
- **Missing-module errors at runtime**: if the built app fails with a
  `ModuleNotFoundError` for something not already imported in
  `desktop_launcher.py`, add an `import` for it there (forcing PyInstaller
  to bundle it) and rebuild, or add `--hidden-import <module>` to the
  `pyinstaller` command.
- **It's still a networked app, not an offline one**: since it needs to
  reach PostgreSQL and `source_folder` still needs to be a path the
  executable's machine can read, this packaging mainly saves the "install
  Python and pip install everything" step for the machine running the UI —
  it doesn't make the app work without a database.

## Testing

```bash
source .venv/bin/activate
pytest
```

Tests cover two layers:

- **Pure logic, no database**: filename period parsing, column-header
  normalization, Excel parsing (`header_row`/`start_col` handling,
  required-column validation), frozen-executable config path resolution
  (`tests/test_frozen_config.py` — see
  [Standalone executable](#standalone-executable-pyinstaller)), the
  `priority`/`reorder_status` classification ladder
  (`tests/test_reorder_logic.py` — mirrors the `CASE` expressions baked
  into `mv_sales_fact`'s SQL; if you change a threshold, change it in
  both places), and the `blocking_button` disable-while-busy UI helper
  (`tests/test_ui_helpers.py`, via a mocked `st.button`/`st.rerun`).
- **Service logic against an in-memory SQLite database** (`tests/test_settings_service.py`,
  `tests/test_ingestion_service.py`): `SettingsService`'s aggregated,
  field-labeled validation errors, and `IngestionService`'s transactional
  behavior — specifically, that the `ingested_files` row for a file is
  committed (and visible from a *separate* connection, standing in for
  Postgres' raw `COPY` connection) before that file's rows are bulk-loaded,
  and that a failed bulk load removes the `ingested_files` row again rather
  than leaving it orphaned. These tests use SQLite as a lightweight stand-in
  for exercising real transaction/commit ordering, not for testing
  Postgres-specific SQL (`COPY`, `REFRESH MATERIALIZED VIEW ... CONCURRENTLY`,
  `ANY()`), which the tests replace with a stub.

`mv_sales_fact`'s actual SQL (the `CREATE MATERIALIZED VIEW` in
`alembic/versions/0004_..._mv_sales_fact_reorder_columns.py`, and
`DashboardService.query()`'s `DISTINCT ON` collapse) is Postgres-specific
and isn't covered by the automated suite above — it was manually verified
end-to-end against a real local PostgreSQL 16 instance while building this
feature (migrations applied cleanly; the computed `total_sales_qty`,
`average_daily_sales`, `priority`, `stock_lasts_until`, `reorder_date`, and
`reorder_status` values were hand-checked against known inputs and matched
exactly — see the worked example in the
[mv_sales_fact section](#mv_sales_fact-time-range-buckets--reorder-planning)).
That verification isn't automated/repeatable in CI, though — add it as a
`testcontainers`-based integration test if CI has Docker available.

## Project layout

```
main.py                          # Entry point: streamlit run main.py
desktop_launcher.py               # PyInstaller entry point (see Standalone executable)
app/
  config/                        # pydantic-settings, dev/prod segregated (+ frozen-exe path resolution)
  database.py                    # SQLAlchemy engine/session (cached resources)
  models/                        # ORM models: AppSetting, IngestedFile, SalesFact, ProductSupplierLeadTime
  services/
    settings_service.py          # SETTING_DEFINITIONS registry + typed get/set + aggregated SettingsValidationError
    file_parser_service.py       # Excel -> normalized DataFrame
    ingestion_service.py         # scan/diff/COPY bulk-load orchestration (commit-before-copy FK ordering, cleanup-on-failure)
    lead_time_service.py         # upload/replace + update for lead times (also refreshes mv_sales_fact)
    dashboard_service.py         # time-range-filtered, branch/product-collapsed reads from mv_sales_fact
    reorder_logic.py             # plain-Python reference copy of the priority/reorder_status thresholds baked into mv_sales_fact's SQL
    materialized_view_service.py # REFRESH MATERIALIZED VIEW [CONCURRENTLY]
  views/
    base.py                      # BaseView ABC (title + error boundary)
    settings_view.py             # initial full-page form + sidebar form
    dashboard_view.py            # ingestion trigger, empty-state, time-range filter, reorder-planning grid
    lead_time_view.py            # update grid + bulk upload
  utils/
    ui.py                        # blocking_button() -- disables a button while its action is in flight
    filename_parser.py           # period_start/period_end from file name
    column_normalization.py      # "Pending PO" -> "pending_po"
    logging_config.py
alembic/                         # migrations (env.py wired to app config)
scripts/                         # lifecycle/migration/dev/ingestion/build helper scripts
tests/                           # pytest suite (pure-logic + SQLite-backed service coverage)
```

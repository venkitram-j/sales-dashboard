# Inventory & Supply Chain App

A Streamlit application for ingesting branch sales/inventory data from Excel
files into PostgreSQL, browsing it on a dashboard, and managing
product-supplier lead times used for order/reorder planning.

## Contents

- [Architecture](#architecture)
- [Data model](#data-model)
- [Features](#features)
- [File naming convention (required)](#file-naming-convention-required)
- [Getting started (development)](#getting-started-development)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [Managing users](#managing-users)
- [Scripts](#scripts)
- [Production deployment](#production-deployment)
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
- **Authentication**: username/password login backed by a `users` table
  (bcrypt-hashed passwords via `app/utils/security.py`). Session state
  (`st.session_state`) tracks who's logged in for the lifetime of the
  browser session. An optional "remember me" cookie
  (`app/utils/cookies.py` + a `user_sessions` table of hashed, expiring
  tokens) persists login across full browser restarts — see
  [Authentication](#1-authentication) for details. Accounts are managed
  with `scripts/manage_users.py` — there is no sign-up UI.
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
| `users` | Login accounts (username + bcrypt password hash) for the Authentication component |
| `user_sessions` | Hashed 'remember me' session tokens (see Authentication below), each tied to a user and an expiry |
| `app_settings` | Key/value store for app configuration (see below) |
| `ingested_files` | One row per source Excel file, tracking ingestion state, mtime, size, and parsed period |
| `sales_fact` | One row per product/branch record parsed from a source file |
| `product_supplier_lead_time` | Lead time (days) per product_code/buyer mapping |
| `mv_sales_fact` (materialized view) | Read-optimized copy of `sales_fact`, refreshed after ingestion |
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

### 1. Authentication
- A single **Login** page (`app/views/login_view.py`) is the only thing an
  unauthenticated visitor can see — username + password, submitted via a
  `st.form`. There is no self-service sign-up.
- Passwords are stored as bcrypt hashes (`app/utils/security.py`) in the
  `users` table, never in plaintext. `authenticate()` returns the same
  generic "Invalid username or password" outcome whether the username
  doesn't exist, the account is inactive, or the password is wrong, so the
  login form doesn't leak which case occurred.
- On successful login, `st.session_state` records the username/user id for
  the rest of that browser session:
  - If it's the app's initial run (no `source_folder` configured yet), the
    **Settings** initial-setup page is shown next.
  - Otherwise, the app proceeds straight to the **Dashboard**.
- A **"Remember me on this device"** checkbox on the login form persists
  the login across browser restarts:
  - On check, a random 256-bit token is generated
    (`app/utils/security.py::generate_session_token`). Only its SHA-256
    hash is stored server-side, in a `user_sessions` row with an
    expiry (`REMEMBER_ME_DAYS`, default 30); the raw token is set as an
    HTTP-only-unavailable-but-`SameSite=Lax` cookie in the browser
    (`app/utils/cookies.py`).
  - On every subsequent app load, `try_auto_login()` reads that cookie via
    Streamlit's built-in `st.context.cookies`, validates it against
    `user_sessions` (checking expiry and that the account is still
    active), and — if valid — signs the session in automatically with no
    form. An invalid/expired/revoked cookie is cleared and the user sees
    the normal login form.
  - Logging out revokes that session server-side and clears the cookie
    (`app/views/login_view.py::log_out`), so the "remember me" cookie
    can't be reused afterward.
  - Changing a user's password or deactivating their account
    (`scripts/manage_users.py`) revokes **all** of that user's remember-me
    sessions immediately, so a stolen/old cookie stops working right away.
  - Cookie reads use Streamlit's native `st.context.cookies` (no extra
    dependency); cookie writes use a small inline `<script>` snippet via
    `st.components.v1.html`, since Streamlit has no built-in API to set
    cookies yet ([streamlit/streamlit#9421](https://github.com/streamlit/streamlit/issues/9421)).
    This keeps the feature dependency-free rather than relying on a
    third-party cookie component.
- Every authenticated page shows a top bar (`app/views/topbar.py`) with
  *"Logged in as `<username>`"* and a **Log out** button, right-aligned
  above the page content. Logging out clears the session state and returns
  to the Login page.
- Accounts are provisioned and managed entirely through
  `scripts/manage_users.py` — see [Managing users](#managing-users).

### 2. Settings
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

### 3. Dashboard
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
- Filters (`product_code`, `branch` multiselects) and a free-text search
  (matches `product_code`, `branch`, `description`, `admin`, `buyer`) all
  query `mv_sales_fact`, never `sales_fact` directly.

### 4. Product-Supplier Lead Time
- An editable grid (`st.data_editor`) at the top of the page lets you update
  `lead_days` for existing product/buyer mappings; **Save Changes** persists
  edits and refreshes `mv_product_supplier_lead_time`.
- Below that, uploading an Excel file (columns: `Product Code`, `Buyer`,
  `Lead Days`) **replaces the entire table** — all existing rows are
  deleted and the uploaded rows are inserted — then the materialized view is
  refreshed. Missing/blank `Lead Days` values fall back to
  `app_settings.default_lead_days`.

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

# Create your first login account (no default/seed account exists)
python scripts/manage_users.py add jane.doe

# Run the app
./scripts/run_dev.sh
```

The app opens in your browser (default `http://localhost:8501`). Log in
with the account you just created; since this is the first run, you'll see
the initial setup form next — point `source_folder` at a directory
containing correctly-named `.xlsx` files (see naming convention above) and
submit.

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
| `REMEMBER_ME_DAYS` | How many days a "remember me" login session stays valid (default 30) |

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

## Managing users

There is no sign-up UI. Accounts are created and maintained with
`scripts/manage_users.py`, which talks to the same database as the app
(respecting `APP_ENV`/`.env` the same way the other scripts do).

```bash
# Create a user (prompts for a password, hidden input, with confirmation)
python scripts/manage_users.py add jane.doe

# Non-interactive (e.g. scripted provisioning) -- avoid this on shared
# shells since the password ends up in shell history
python scripts/manage_users.py add jane.doe --password 'a-strong-password'

# Change an existing user's password
python scripts/manage_users.py set-password jane.doe

# Disable / re-enable login access without deleting the account
python scripts/manage_users.py deactivate jane.doe
python scripts/manage_users.py activate jane.doe

# List all users, their active status, and last login time
python scripts/manage_users.py list

# Delete expired "remember me" session rows (safe to run on a periodic
# schedule, e.g. a daily cron job -- rows aren't a security risk once
# expired, this is just housekeeping)
python scripts/manage_users.py purge-sessions
```

Passwords must be at least 8 characters; they're hashed with bcrypt
(`app/utils/security.py`) before being stored — the script never writes
plaintext to the database. Changing a user's password or deactivating their
account immediately revokes all of that user's "remember me" sessions, so
an old device can't stay logged in past either action. Run
`python scripts/manage_users.py add` (with no `--password`) to create the
first account after a fresh `./scripts/setup_dev.sh` / `./scripts/migrate.sh`,
since the app itself has no way to create the first user.

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
| `manage_users.py` | Add users, change passwords, activate/deactivate accounts, list users, purge expired remember-me sessions |

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

## Testing

```bash
source .venv/bin/activate
pytest
```

Tests cover the pure-logic pieces that don't require a live database:
filename period parsing, column-header normalization, and Excel parsing
(`header_row`/`start_col` handling, required-column validation). Extend with
integration tests against a real/test Postgres instance (e.g. via
`testcontainers`) for the ingestion, settings, and lead-time services if
CI has Docker available.

## Project layout

```
main.py                          # Entry point: streamlit run main.py
app/
  config/                        # pydantic-settings, dev/prod segregated
  database.py                    # SQLAlchemy engine/session (cached resources)
  models/                        # ORM models: User, UserSession, AppSetting, IngestedFile, SalesFact, ProductSupplierLeadTime
  services/
    auth_service.py              # authenticate + remember-me sessions + user provisioning (used by manage_users.py)
    settings_service.py          # SETTING_DEFINITIONS registry + typed get/set
    file_parser_service.py       # Excel -> normalized DataFrame
    ingestion_service.py         # scan/diff/COPY bulk-load orchestration
    lead_time_service.py         # upload/replace + update for lead times
    dashboard_service.py         # filtered reads from mv_sales_fact
    materialized_view_service.py # REFRESH MATERIALIZED VIEW [CONCURRENTLY]
  views/
    base.py                      # BaseView ABC (title + error boundary)
    login_view.py                # the Authentication component's only page + remember-me + auto-login
    topbar.py                    # "Logged in as ..." + Log out, shown on every page
    settings_view.py             # initial full-page form + sidebar form
    dashboard_view.py            # ingestion trigger, filters, data grid
    lead_time_view.py            # update grid + bulk upload
  utils/
    security.py                  # bcrypt password hashing + session token generation/hashing
    cookies.py                   # read (st.context.cookies) / write (inline <script>) browser cookies
    filename_parser.py           # period_start/period_end from file name
    column_normalization.py      # "Pending PO" -> "pending_po"
    logging_config.py
alembic/                         # migrations (env.py wired to app config)
scripts/                         # lifecycle/migration/dev/user-management helper scripts
tests/                           # pytest suite (pure-logic coverage)
```

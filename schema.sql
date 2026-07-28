-- Sales dashboard schema. Safe to run repeatedly (IF NOT EXISTS everywhere).

-- Tracks which source files have been ingested, and when, so daily runs
-- only process new or changed files. period_start/period_end record what
-- date range the FILE covers overall (parsed from its file name) — used
-- when the file has no per-row date column.
CREATE TABLE IF NOT EXISTS ingested_files (
    file_name       TEXT PRIMARY KEY,
    file_mtime      DOUBLE PRECISION NOT NULL,
    row_count       INTEGER,
    period_start    DATE,
    period_end      DATE,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'ok',   -- 'ok' or 'error'
    error_message   TEXT
);

-- One row per (product, branch[, date]) sales record, tagged with the file
-- it came from so a re-ingested file can cleanly replace its own rows.
-- sale_date is populated when the file has a real per-row date column;
-- period_start/period_end are denormalized from the file's parsed period
-- so date-range filtering works even for files with no per-row dates.
CREATE TABLE IF NOT EXISTS sales_fact (
    id            BIGSERIAL PRIMARY KEY,
    product_code  TEXT NOT NULL,
    description   TEXT NOT NULL,
    branch        TEXT NOT NULL,
    period_start  DATE NOT NULL,
    period_end    DATE NOT NULL,
    sales_qty     NUMERIC NOT NULL,
    pending_po    NUMERIC NOT NULL,
    admin         TEXT NOT NULL,
    buyer         TEXT NOT NULL,
    source_file   TEXT NOT NULL REFERENCES ingested_files(file_name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sales_fact_product     ON sales_fact (product_code);
CREATE INDEX IF NOT EXISTS idx_sales_fact_description ON sales_fact (description);
CREATE INDEX IF NOT EXISTS idx_sales_fact_branch      ON sales_fact (branch);
CREATE INDEX IF NOT EXISTS idx_sales_fact_source_file ON sales_fact (source_file);
CREATE INDEX IF NOT EXISTS idx_sales_fact_prod_branch ON sales_fact (product_code, branch);

-- Configuration table for reorder parameters
CREATE TABLE IF NOT EXISTS reorder_config (
    config_key   TEXT PRIMARY KEY,
    config_value INTEGER NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Insert default values if not exists
INSERT INTO reorder_config (config_key, config_value)
VALUES
    ('ORDER_PROCESS_TIME', 4),
    ('PRIORITY_BUFFER_HIGH', 0),
    ('PRIORITY_BUFFER_MEDIUM', 2),
    ('PRIORITY_BUFFER_LOW', 4)
ON CONFLICT (config_key) DO NOTHING;

-- Lead-time table for reorder planning, defaulting to 15 days.
CREATE TABLE IF NOT EXISTS lead_time (
    product_code TEXT NOT NULL,
    buyer        TEXT NOT NULL,
    lead_days    INTEGER NOT NULL DEFAULT 15,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_code, buyer)
);

-- Materialized view: total sales by product and branch
DROP MATERIALIZED VIEW IF EXISTS product_branch_sales;

CREATE MATERIALIZED VIEW product_branch_sales AS
WITH recent_sales AS (
    SELECT *
    FROM sales_fact
    WHERE period_end >= CURRENT_DATE - INTERVAL '3 months'
),
summary AS (
    SELECT
        product_code,
        description,
        branch,
        admin,
        buyer,
        MIN(period_start) AS period_start,
        MAX(period_end) AS period_end,
        SUM(sales_qty) AS total_sales_qty,
        SUM(pending_po) AS total_pending_po,
        FLOOR(
            SUM(sales_qty)
            / NULLIF(
                MAX(period_end) - MIN(period_start) + 1,
                0
            )
        )::numeric AS avg_daily_sales
    FROM recent_sales
    GROUP BY product_code, description, branch, admin, buyer
),
reorder_values AS (
    SELECT
        MAX(CASE WHEN config_key = 'ORDER_PROCESS_TIME' THEN config_value END) AS order_process_time,
        MAX(CASE WHEN config_key = 'PRIORITY_BUFFER_HIGH' THEN config_value END) AS priority_buffer_high,
        MAX(CASE WHEN config_key = 'PRIORITY_BUFFER_MEDIUM' THEN config_value END) AS priority_buffer_medium,
        MAX(CASE WHEN config_key = 'PRIORITY_BUFFER_LOW' THEN config_value END) AS priority_buffer_low
    FROM reorder_config
),
base AS (
    SELECT
        s.product_code AS "Product Code",
        s.description AS "Description",
        s.branch AS "Branch",
        s.period_start AS "Period Start",
        s.period_end AS "Period End",
        s.total_sales_qty AS "Total Sales Quantity",
        s.total_pending_po AS "Total Pending PO",
        s.avg_daily_sales AS "Average Daily Sales",
        CASE
            WHEN s.avg_daily_sales >= 1000 THEN 'HIGH'
            WHEN s.avg_daily_sales >= 500 THEN 'MEDIUM'
            ELSE 'LOW'
        END AS "Priority",
        CASE
            WHEN s.avg_daily_sales > 0 THEN
                (
                    s.period_end
                    + INTERVAL '1 day' * FLOOR(s.total_pending_po / NULLIF(s.avg_daily_sales, 0))
                )::date
            ELSE NULL
        END AS "Stock Lasts Until",
        CASE
            WHEN s.avg_daily_sales > 0 THEN
                (
                    s.period_end
                    + INTERVAL '1 day' * FLOOR(s.total_pending_po / NULLIF(s.avg_daily_sales, 0))
                    - INTERVAL '1 day' * (
                        COALESCE(lt.lead_days, 15)
                        - COALESCE(rv.order_process_time, 4)
                    )
                    + INTERVAL '1 day' * COALESCE(
                        CASE
                            WHEN s.avg_daily_sales >= 1000 THEN rv.priority_buffer_high
                            WHEN s.avg_daily_sales >= 500 THEN rv.priority_buffer_medium
                            ELSE rv.priority_buffer_low
                        END,
                        0
                    )
                )::date
            ELSE NULL
        END AS "Reorder Date",
        s.admin AS "Admin",
        s.buyer AS "Buyer",
        COALESCE(lt.lead_days, 15) AS "Lead Time Days"
    FROM summary s
    LEFT JOIN lead_time lt
        ON lt.product_code = s.product_code
        AND lt.buyer = s.buyer
    CROSS JOIN reorder_values rv
)
SELECT
    "Product Code",
    "Description",
    "Branch",
    "Total Sales Quantity",
    "Total Pending PO",
    "Average Daily Sales",
    "Priority",
    "Stock Lasts Until",
    "Reorder Date",
    CASE
        WHEN "Reorder Date" IS NULL THEN 'OK'
        WHEN "Reorder Date"::date <= CURRENT_DATE THEN
            CASE
                WHEN "Priority" = 'HIGH' THEN 'OVERDUE'
                WHEN "Priority" = 'MEDIUM' THEN 'REORDER'
                ELSE 'PLAN'
            END
        WHEN "Reorder Date"::date <= CURRENT_DATE + 2 THEN
            CASE
                WHEN "Priority" = 'HIGH' THEN 'REORDER'
                WHEN "Priority" = 'MEDIUM' THEN 'PLAN'
                ELSE 'OK'
            END
        WHEN "Reorder Date"::date <= CURRENT_DATE + 4 THEN
            CASE
                WHEN "Priority" = 'HIGH' THEN 'PLAN'
                ELSE 'OK'
            END
        ELSE 'OK'
    END AS "Reorder Status",
    "Admin",
    "Buyer",
    "Lead Time Days"
FROM base
ORDER BY "Total Sales Quantity" DESC;

CREATE INDEX IF NOT EXISTS idx_product_branch_sales_product
    ON product_branch_sales ("Product Code");
CREATE INDEX IF NOT EXISTS idx_product_branch_sales_branch
    ON product_branch_sales ("Branch");
CREATE INDEX IF NOT EXISTS idx_sales_fact_period_end
    ON sales_fact (period_end);

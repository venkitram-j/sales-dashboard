"""
Sales Dashboard — reads pre-ingested sales data from Postgres (populated by
ingest.py) and lets the team filter, view KPIs/trends, and attach a
status + remark per (product, branch).

Run with:
    streamlit run dashboard_app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import config
from db import get_conn, init_schema

st.set_page_config(page_title="Sales Dashboard", layout="wide")

CONFIG_FILE = Path("reorder_config.json")

# ---------------------------------------------------------------------------
# DB setup (cached across reruns within a session; cheap to call anyway)
# ---------------------------------------------------------------------------

@st.cache_resource
def ensure_schema():
    init_schema()
    return True


ensure_schema()

# ---------------------------------------------------------------------------
# Load and display materialized view and lead-time data
# ---------------------------------------------------------------------------

st.title("📊 Sales Dashboard")

# Refresh button for materialized view
col1, col2 = st.columns([1, 10])
with col1:
    if st.button("🔄 Refresh Data"):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW product_branch_sales")
            conn.commit()
        st.success("Data refreshed!")
        st.cache_data.clear()


@st.cache_data
def load_view_data():
    """Load data from the materialized view."""
    with get_conn() as conn:
        query = "SELECT * FROM product_branch_sales"
        return pd.read_sql(query, conn)


@st.cache_data
def load_lead_time_data():
    """Load data from the lead_time table."""
    with get_conn() as conn:
        query = "SELECT product_code, buyer, lead_days, updated_at FROM lead_time ORDER BY product_code, buyer"
        df = pd.read_sql(query, conn)
    df["updated_at"] = pd.to_datetime(df["updated_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    return df.rename(columns={
        "product_code": "Product Code",
        "buyer": "Buyer",
        "lead_days": "Lead Days",
        "updated_at": "Updated At",
    })


def update_lead_time_from_dataframe(df):
    """Update the lead_time table using an uploaded DataFrame."""
    required_cols = {"product_code", "buyer", "lead_days"}
    if not required_cols.issubset({c.lower() for c in df.columns}):
        raise ValueError("Uploaded file must contain product_code, buyer, and lead_days columns.")

    df = df.rename(columns={c: c.lower() for c in df.columns})
    df = df[["product_code", "buyer", "lead_days"]].copy()
    df["lead_days"] = pd.to_numeric(df["lead_days"], errors="coerce").fillna(config.LEAD_TIME).astype(int)
    df = df.drop_duplicates(subset=["product_code", "buyer"], keep="last")

    pairs = [(row.product_code, row.buyer) for row in df.itertuples(index=False)]
    existing_map = {}
    if pairs:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT product_code, buyer, lead_days FROM lead_time WHERE (product_code, buyer) IN %s",
                    (tuple(pairs),)
                )
                for product_code, buyer, lead_days in cur.fetchall():
                    existing_map[(product_code, buyer)] = int(lead_days)

    inserted = 0
    updated = 0
    unchanged = 0
    changed_rows = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                key = (row["product_code"], row["buyer"])
                lead_days = int(row["lead_days"])
                existing_value = existing_map.get(key)
                if existing_value is None:
                    inserted += 1
                    changed_rows.append({"product_code": key[0], "buyer": key[1], "lead_days": lead_days, "change": "inserted"})
                elif existing_value != lead_days:
                    updated += 1
                    changed_rows.append({"product_code": key[0], "buyer": key[1], "lead_days": lead_days, "change": "updated"})
                else:
                    unchanged += 1

                cur.execute(
                    "INSERT INTO lead_time (product_code, buyer, lead_days, updated_at) VALUES (%s, %s, %s, now()) "
                    "ON CONFLICT (product_code, buyer) DO UPDATE SET lead_days = EXCLUDED.lead_days, updated_at = EXCLUDED.updated_at",
                    (key[0], key[1], lead_days)
                )
        conn.commit()

    st.cache_data.clear()
    changes_df = pd.DataFrame(changed_rows) if changed_rows else pd.DataFrame(columns=["product_code", "buyer", "lead_days", "change"])
    changes_df = changes_df.rename(columns={
        "product_code": "Product Code",
        "buyer": "Buyer",
        "lead_days": "Lead Days",
        "change": "Change",
    })
    return {
        "processed": len(df),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "changes": changes_df,
    }


@st.cache_data
def load_reorder_config_data():
    """Load data from the reorder_config table."""
    with get_conn() as conn:
        query = "SELECT config_key, config_value, updated_at FROM reorder_config ORDER BY config_key"
        df = pd.read_sql(query, conn)
    df["updated_at"] = pd.to_datetime(df["updated_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    return df.rename(columns={
        "config_key": "Config Key",
        "config_value": "Config Value",
        "updated_at": "Updated At",
    })


def update_reorder_config_from_dataframe(df):
    """Update the reorder_config table using an uploaded DataFrame."""
    required_cols = {"config_key", "config_value"}
    if not required_cols.issubset({c.lower() for c in df.columns}):
        raise ValueError("Uploaded file must contain config_key and config_value columns.")

    df = df.rename(columns={c: c.lower() for c in df.columns})
    df = df[["config_key", "config_value"]].copy()
    df["config_value"] = pd.to_numeric(df["config_value"], errors="coerce").astype(pd.Int64Dtype())
    df = df.drop_duplicates(subset=["config_key"], keep="last")

    keys = [row.config_key for row in df.itertuples(index=False)]
    existing_map = {}
    if keys:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM reorder_config WHERE config_key IN %s",
                    (tuple(keys),)
                )
                for config_key, config_value in cur.fetchall():
                    existing_map[config_key] = int(config_value)

    inserted = 0
    updated = 0
    unchanged = 0
    changed_rows = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                key = row["config_key"]
                value = int(row["config_value"])
                existing_value = existing_map.get(key)
                if existing_value is None:
                    inserted += 1
                    changed_rows.append({"config_key": key, "config_value": value, "change": "inserted"})
                elif existing_value != value:
                    updated += 1
                    changed_rows.append({"config_key": key, "config_value": value, "change": "updated"})
                else:
                    unchanged += 1

                cur.execute(
                    "INSERT INTO reorder_config (config_key, config_value, updated_at) VALUES (%s, %s, now()) "
                    "ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = EXCLUDED.updated_at",
                    (key, value)
                )
        conn.commit()

    st.cache_data.clear()
    changes_df = pd.DataFrame(changed_rows) if changed_rows else pd.DataFrame(columns=["config_key", "config_value", "change"])
    changes_df = changes_df.rename(columns={
        "config_key": "Config Key",
        "config_value": "Config Value",
        "change": "Change",
    })
    return {
        "processed": len(df),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "changes": changes_df,
    }


df_view = load_view_data()
lead_time_df = load_lead_time_data()
reorder_config_df = load_reorder_config_data()

tabs = st.tabs(["Sales Summary", "Supplier Product Lead Time", "Summary Config"])

with tabs[0]:
    st.subheader("Product Sales Summary")

    if df_view.empty:
        st.info("No sales data available yet.")
    else:
        product_code_options = sorted({str(value) for value in df_view["Product Code"].dropna().unique()})
        branch_options = sorted({str(value) for value in df_view["Branch"].dropna().unique()})

        filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 3])
        with filter_col1:
            selected_product_codes = st.multiselect("Product Code", options=product_code_options, default=[])
        with filter_col2:
            selected_branches = st.multiselect("Branch", options=branch_options, default=[])
        with filter_col3:
            search_term = st.text_input(
                "Search",
                placeholder="Search product code, branch, description, admin, buyer"
            )

        filtered_df = df_view.copy()
        if selected_product_codes:
            filtered_df = filtered_df[
                filtered_df["Product Code"].astype(str).isin(selected_product_codes)
            ]
        if selected_branches:
            filtered_df = filtered_df[
                filtered_df["Branch"].astype(str).isin(selected_branches)
            ]
        if search_term.strip():
            search_value = search_term.strip().lower()
            searchable_columns = ["Product Code", "Branch", "Description", "Admin", "Buyer"]
            mask = filtered_df[searchable_columns].fillna("").astype(str).apply(
                lambda col: col.str.contains(search_value, case=False, na=False)
            ).any(axis=1)
            filtered_df = filtered_df[mask]

        st.caption(f"Showing {len(filtered_df)} row(s)")
        st.dataframe(filtered_df, width='stretch')

with tabs[1]:
    st.subheader("Lead Time Table")
    st.write(
        "Upload an Excel file containing `product_code`, `buyer`, and `lead_days`. "
        "The latest row per product_code/buyer pair will be kept."
    )
    uploaded_file = st.file_uploader("Upload lead time Excel file", type=["xlsx", "xls"])
    if uploaded_file is not None:
        try:
            excel_df = pd.read_excel(uploaded_file)
            result = update_lead_time_from_dataframe(excel_df)
            st.success("Lead time table updated successfully.")
            st.write(
                f"Processed {result['processed']} rows: "
                f"{result['inserted']} inserted, {result['updated']} updated, {result['unchanged']} unchanged."
            )
            if not result['changes'].empty:
                st.subheader("Updated Rows")
                st.dataframe(result['changes'], width='stretch')
            lead_time_df = load_lead_time_data()
        except Exception as exc:
            st.error(f"Failed to load uploaded file: {exc}")

    if lead_time_df.empty:
        st.info("No lead time data available yet.")
    else:
        product_code_options = sorted({str(value) for value in lead_time_df["Product Code"].dropna().unique()})

        filter_col1, filter_col2 = st.columns([2, 4])
        with filter_col1:
            selected_product_codes = st.multiselect("Product Code", options=product_code_options, default=[])
        with filter_col2:
            search_term = st.text_input(
                "Search",
                placeholder="Search product code or buyer"
            )

        filtered_lead_time_df = lead_time_df.copy()
        if selected_product_codes:
            filtered_lead_time_df = filtered_lead_time_df[
                filtered_lead_time_df["Product Code"].astype(str).isin(selected_product_codes)
            ]
        if search_term.strip():
            search_value = search_term.strip().lower()
            mask = filtered_lead_time_df[["Product Code", "Buyer"]].fillna("").astype(str).apply(
                lambda col: col.str.contains(search_value, case=False, na=False)
            ).any(axis=1)
            filtered_lead_time_df = filtered_lead_time_df[mask]

        st.caption(f"Showing {len(filtered_lead_time_df)} row(s)")
        st.dataframe(filtered_lead_time_df, width='stretch')

with tabs[2]:
    st.subheader("Reorder Config")
    st.write(
        "Upload an Excel file containing `config_key` and `config_value`. "
        "The latest value per config_key will be applied."
    )
    config_file = st.file_uploader("Upload reorder config Excel file", type=["xlsx", "xls"], key="reorder_config")
    if config_file is not None:
        try:
            config_df = pd.read_excel(config_file)
            config_result = update_reorder_config_from_dataframe(config_df)
            st.success("Reorder config updated successfully.")
            st.write(
                f"Processed {config_result['processed']} rows: "
                f"{config_result['inserted']} inserted, {config_result['updated']} updated, {config_result['unchanged']} unchanged."
            )
            if not config_result['changes'].empty:
                st.subheader("Updated Config Rows")
                st.dataframe(config_result['changes'], width='stretch')
            reorder_config_df = load_reorder_config_data()
        except Exception as exc:
            st.error(f"Failed to load uploaded file: {exc}")

    st.dataframe(reorder_config_df, width='stretch')

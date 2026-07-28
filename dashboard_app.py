"""
Sales Dashboard — reads pre-ingested sales data from Postgres (populated by
ingest.py) per (product, branch).

Run with:
    streamlit run dashboard_app.py
"""

import os
import pandas as pd
import streamlit as st

from db import get_conn, init_schema, get_settings, save_settings
from ingest import normalize_col, denormalize_col, run_ingestion

st.set_page_config(page_title="Sales Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# DB setup (cached across reruns within a session; cheap to call anyway)
# ---------------------------------------------------------------------------

@st.cache_resource
def ensure_schema():
    init_schema()
    return True


ensure_schema()
run_ingestion()

# ---------------------------------------------------------------------------
# Settings form (source folder, header row, start column, columns to read)
# — shared by the first-run gate below and the sidebar "Edit settings"
# expander further down.
# ---------------------------------------------------------------------------

def render_settings_form(current, key_prefix):
    with st.form(f"{key_prefix}_settings_form"):
        source_folder = st.text_input(
            "Source folder (path on the server running this app)",
            value=current["source_folder"],
            placeholder=r"e.g. /mnt/company_share/sales_files",
        )
        c1, c2 = st.columns(2)
        with c1:
            start_col = st.text_input("Start column", value=current["start_col"])
        with c2:
            header_row = st.number_input("Header row #", min_value=1, value=current["header_row"], step=1)

        if key_prefix == "setup":
            c3, c4 = st.columns(2)
            with c3:
                order_process_days = st.number_input(
                    "Order Process Days", min_value=0, value=current["order_process_days"], step=1)
    
            with c4:
                default_lead_days = st.number_input(
                    "Default Lead Time for Products in Days", min_value=0, value=current["default_lead_days"], step=1)
            
            c5, c6 ,c7 = st.columns(3)
            with c5:
                order_buffer_high_days = st.number_input(
                    "Order Buffer for High Priority Products", min_value=0, value=current["order_buffer_high_days"], step=1)

            with c6:
                order_buffer_medium_days = st.number_input(
                    "Order Buffer for Medium Priority Products", min_value=0, value=current["order_buffer_medium_days"], step=1)

            with c7:
                order_buffer_low_days = st.number_input(
                    "Order Buffer for Low Priority Products", min_value=0, value=current["order_buffer_low_days"], step=1)
        else:
            order_process_days = st.number_input(
                "Order Process Days", min_value=0, value=current["order_process_days"], step=1)

            default_lead_days = st.number_input(
                "Default Lead Time for Products in Days", min_value=0, value=current["default_lead_days"], step=1)

            order_buffer_high_days = st.number_input(
                "Order Buffer for High Priority Products", min_value=0, value=current["order_buffer_high_days"], step=1)

            order_buffer_medium_days = st.number_input(
                "Order Buffer for Medium Priority Products", min_value=0, value=current["order_buffer_medium_days"], step=1)

            order_buffer_low_days = st.number_input(
                "Order Buffer for Low Priority Products", min_value=0, value=current["order_buffer_low_days"], step=1)

        submitted = st.form_submit_button("Save settings")

    if not submitted:
        return False

    folder = source_folder.strip()
    if not folder:
        st.error("Source folder is required.")
        return False
    if not os.path.isdir(folder):
        st.error(f"'{folder}' doesn't exist or isn't accessible from this server.")
        return False

    data = {
        "source_folder": source_folder.strip(),
        "header_row": str(int(header_row)),
        "start_col": start_col.strip().upper() or "A",
        "order_process_days": str(int(order_process_days)),
        "default_lead_days": str(int(default_lead_days)),
        "order_buffer_high_days": str(int(order_buffer_high_days)),
        "order_buffer_medium_days": str(int(order_buffer_medium_days)),
        "order_buffer_low_days": str(int(order_buffer_low_days)),
    }
    save_settings(data)
    get_cached_settings.clear()
    st.success("Settings saved.")
    return True


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_settings():
    return get_settings()


settings = get_cached_settings()

if not settings["source_folder"]:
    st.title("⚙️ Set up the data source")
    st.write(
        "Before the dashboard can load, tell it where to find your Excel files "
        "and how they're formatted. This is stored in the database, so it only "
        "needs to be set once (from anywhere on the team)."
    )
    if render_settings_form(settings, key_prefix="setup"):
        st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Load and display materialized view and lead-time data
# ---------------------------------------------------------------------------

st.title("📊 Sales Dashboard")

st.sidebar.header("📁 Dashboard Config")

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    with st.spinner("Refreshing Data — this scans the source folder for new/changed files…"):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW product_branch_sales")
            conn.commit()
        st.success("Data refreshed!")
        st.cache_data.clear()

with st.sidebar.expander("⚙️ Edit source settings"):
    if render_settings_form(settings, key_prefix="edit"):
        st.rerun()


@st.cache_data
def load_view_data():
    """Load data from the materialized view."""
    with get_conn() as conn:
        query = "SELECT * FROM product_branch_sales"
        return pd.read_sql(query, conn)


@st.cache_data
def load_lead_days_data():
    """Load data from the lead_days table."""
    with get_conn() as conn:
        query = "SELECT product_code, buyer, days, updated_at FROM lead_days ORDER BY product_code, buyer"
        df = pd.read_sql(query, conn)

    df["updated_at"] = pd.to_datetime(df["updated_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    return df.rename(columns={c: denormalize_col(c) for c in df.columns})


def update_lead_days_from_dataframe(df):
    """Update the lead_days table using an uploaded DataFrame."""
    LEAD_DAYS_TABLE_COLUMNS = ["Product Code", "Buyer", "Days"]
    missing = [c for c in LEAD_DAYS_TABLE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing expected column(s): {', '.join(missing)} in Lead Days excel")

    df = df.rename(columns={c: normalize_col(c) for c in df.columns})
    df["days"] = pd.to_numeric(df["days"], errors="coerce").fillna(settings["default_lead_days"]).astype(int)
    df = df.drop_duplicates(subset=["product_code", "buyer"], keep="last")

    pairs = [(row.product_code, row.buyer) for row in df.itertuples(index=False)]
    existing_map = {}
    if pairs:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT product_code, buyer, days FROM lead_time WHERE (product_code, buyer) IN %s",
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
                days = int(row["days"])
                existing_value = existing_map.get(key)
                if existing_value is None:
                    inserted += 1
                    changed_rows.append({"product_code": key[0], "buyer": key[1], "days": days, "change": "inserted"})
                elif existing_value != days:
                    updated += 1
                    changed_rows.append({"product_code": key[0], "buyer": key[1], "days": days, "change": "updated"})
                else:
                    unchanged += 1

                cur.execute(
                    "INSERT INTO lead_time (product_code, buyer, days, updated_at) VALUES (%s, %s, %s, now()) "
                    "ON CONFLICT (product_code, buyer) DO UPDATE SET days = EXCLUDED.days, updated_at = EXCLUDED.updated_at",
                    (key[0], key[1], days)
                )
        conn.commit()

    st.cache_data.clear()
    changes_df = pd.DataFrame(changed_rows) if changed_rows else pd.DataFrame(columns=["product_code", "buyer", "days", "change"])
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

df_view = load_view_data()
lead_time_df = load_lead_days_data()

tabs = st.tabs(["Sales Summary", "Supplier Product Lead Time"])

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
    st.subheader("Lead Days Table")
    st.write(
        "Upload an Excel file containing `Product Code`, `Buyer`, and `Days`. "
        "The latest row per Product Code/Buyer pair will be kept."
    )
    uploaded_file = st.file_uploader("Upload lead time Excel file", type=["xlsx", "xls"])
    if uploaded_file is not None:
        try:
            excel_df = pd.read_excel(uploaded_file)
            result = update_lead_days_from_dataframe(excel_df)
            st.success("Lead days table updated successfully.")
            st.write(
                f"Processed {result['processed']} rows: "
                f"{result['inserted']} inserted, {result['updated']} updated, {result['unchanged']} unchanged."
            )
            if not result['changes'].empty:
                st.subheader("Updated Rows")
                st.dataframe(result['changes'], width='stretch')
            lead_time_df = load_lead_days_data()
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


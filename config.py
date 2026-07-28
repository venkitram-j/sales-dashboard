"""Central configuration, loaded from environment variables / .env."""

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

SOURCE_FOLDER = os.environ.get("SOURCE_FOLDER", "")
HEADER_ROW = int(os.environ.get("HEADER_ROW", "5"))
START_COL = os.environ.get("START_COL", "B")

_cols = os.environ.get("COLUMNS_TO_READ", "")
COLUMNS_TO_READ = [c.strip() for c in _cols.split(",") if c.strip()]

PRODUCT_COL = os.environ.get("PRODUCT_COL", "")
DESCRIPTION_COL = os.environ.get("DESCRIPTION_COL", "")
BRANCH_COL = os.environ.get("BRANCH_COL", "")
SALES_COL = os.environ.get("SALES_COL", "")
PENDING_PO_COL = os.environ.get("PENDING_PO_COL", "")
ADMIN_COL = os.environ.get("ADMIN_COL", "")
BUYER_COL = os.environ.get("BUYER_COL", "")

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# Reorder configuration
ORDER_PROCESS_TIME = int(os.environ.get("ORDER_PROCESS_TIME", "4"))
PRIORITY_BUFFER_HIGH = int(os.environ.get("PRIORITY_BUFFER_HIGH", "0"))
PRIORITY_BUFFER_MEDIUM = int(os.environ.get("PRIORITY_BUFFER_MEDIUM", "2"))
PRIORITY_BUFFER_LOW = int(os.environ.get("PRIORITY_BUFFER_LOW", "4"))
LEAD_TIME = int(os.environ.get("LEAD_TIME", "15"))


def validate():
    problems = []
    if not DATABASE_URL:
        problems.append("DATABASE_URL is not set")
    if not SOURCE_FOLDER:
        problems.append("SOURCE_FOLDER is not set")
    if not COLUMNS_TO_READ:
        problems.append("COLUMNS_TO_READ is not set")
    
    # Validate that each required column is in COLUMNS_TO_READ
    required_columns = {
        "PRODUCT_COL": PRODUCT_COL,
        "DESCRIPTION_COL": DESCRIPTION_COL,
        "BRANCH_COL": BRANCH_COL,
        "SALES_COL": SALES_COL,
        "PENDING_PO_COL": PENDING_PO_COL,
        "ADMIN_COL": ADMIN_COL,
        "BUYER_COL": BUYER_COL
    }
    for col_name, col_value in required_columns.items():
        if COLUMNS_TO_READ and col_value not in COLUMNS_TO_READ:
            problems.append(f"{col_name} '{col_value}' is not in COLUMNS_TO_READ")
    
    return problems

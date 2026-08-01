"""Normalizes Excel column headers ('Product Code') to DB field names
('product_code')."""
from __future__ import annotations

import re

_non_alnum = re.compile(r"[^0-9a-zA-Z]+")


def normalize_column_name(column: str) -> str:
    """'Product Code' -> 'product_code'; 'Pending PO' -> 'pending_po'."""
    cleaned = _non_alnum.sub("_", str(column).strip()).strip("_")
    return cleaned.lower()

from __future__ import annotations

from app.utils.column_normalization import normalize_column_name


def test_normalizes_simple_header():
    assert normalize_column_name("Product Code") == "product_code"


def test_normalizes_acronym_header():
    assert normalize_column_name("Pending PO") == "pending_po"


def test_strips_extra_whitespace_and_punctuation():
    assert normalize_column_name("  Sales   Qty! ") == "sales_qty"


def test_single_word_lowercased():
    assert normalize_column_name("Branch") == "branch"

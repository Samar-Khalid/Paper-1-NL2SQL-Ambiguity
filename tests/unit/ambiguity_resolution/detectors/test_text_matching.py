"""Tests for the deterministic text-matching helpers."""
import pytest

from eaa.ambiguity_resolution.detectors.text_matching import (
    find_phrase,
    find_substring,
    normalize_phrase,
    significant_terms,
    singularize,
    split_terms,
)

pytestmark = pytest.mark.unit


def test_split_terms_offsets() -> None:
    """Tokens carry half-open character offsets into the original text."""
    terms = split_terms("Q4 2024, revenue")
    assert [t.text for t in terms] == ["Q4", "2024", "revenue"]
    assert [(t.start, t.end) for t in terms] == [(0, 2), (3, 7), (9, 16)]
    assert "Q4 2024, revenue"[9:16] == "revenue"


def test_normalize_phrase_joins_terms() -> None:
    """Case, separators, and underscores normalize to a single key."""
    assert normalize_phrase("Net_Revenue") == "net revenue"
    assert normalize_phrase("NET SALES") == "net sales"
    assert normalize_phrase("  Q4,, FY  ") == "q4 fy"


def test_find_phrase_token_contiguous() -> None:
    """The phrase is found as a contiguous, case-insensitive token run."""
    assert find_phrase("What was our net sales?", "net sales") == (13, 22)
    assert find_phrase("Net sales and gross", "net sales") == (0, 9)


def test_find_phrase_ignores_punctuation_in_phrase() -> None:
    """Punctuation inside the phrase is not part of the match."""
    assert find_phrase("orders for Q4", "q4") == (11, 13)


def test_find_phrase_absent_returns_none() -> None:
    """An absent phrase yields None, not a partial token match."""
    assert find_phrase("How many orders?", "revenue") is None
    assert find_phrase("How many open orders?", "opened") is None


def test_find_substring_symbols() -> None:
    """Symbols such as currency markers are found literally."""
    assert find_substring("revenue in $ millions", "$") == (11, 12)
    assert find_substring("plain text", "$") is None


def test_significant_terms_filters_noise() -> None:
    """Stopwords, short terms, and pure digits are excluded."""
    terms = significant_terms("How many active customers of type 3?")
    assert [t.text for t in terms] == ["many", "active", "customers", "type"]


def test_singularize_common_plurals() -> None:
    """Common English plurals reduce to singular forms."""
    assert singularize("regions") == "region"
    assert singularize("cities") == "city"
    assert singularize("sales") == "sale"
    assert singularize("status") == "status"
    assert singularize("gross") == "gross"
    assert singularize("region") == "region"

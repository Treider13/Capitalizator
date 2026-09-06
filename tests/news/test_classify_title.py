"""Title classifier: NFP/PCE tokens, listing is a word, unknown is OTHER."""

from __future__ import annotations

from capitalizator.news_macro.ingest import NEWS_CLASSES
from capitalizator.news_macro.rss import classify_title


def test_fomc_before_cpi() -> None:
    assert classify_title("FOMC and CPI preview") == "FOMC"


def test_cpi_token() -> None:
    assert classify_title("US CPI due at 08:30") == "CPI"


def test_nfp_tokens() -> None:
    assert classify_title("Nonfarm payrolls beat") == "NFP"
    assert classify_title("non-farm payroll") == "NFP"
    assert classify_title("NFP print") == "NFP"
    assert classify_title("Payrolls surprise") == "NFP"


def test_pce_tokens() -> None:
    assert classify_title("Core PCE inflation") == "PCE"
    assert classify_title("Personal consumption expenditures") == "PCE"


def test_nfp_is_not_listing() -> None:
    """Payrolls must not match the listing word."""
    assert classify_title("Nonfarm payrolls") == "NFP"
    assert classify_title("Exchange listing of SOL") == "LISTING"
    assert classify_title("XYZ lists on Bybit") == "LISTING"


def test_hack_etf_sec() -> None:
    assert classify_title("Hot wallet hack") == "HACK"
    assert classify_title("Spot ETF approved") == "ETF"
    assert classify_title("SEC lawsuit filed") == "SEC"


def test_unknown_is_other_not_fomc() -> None:
    assert "OTHER" in NEWS_CLASSES
    assert classify_title("Market wrap: volumes steady") == "OTHER"


def test_watchlist_substring_is_not_listing() -> None:
    assert classify_title("Added to watchlist") == "OTHER"

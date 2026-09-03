"""D-22: no-entry windows sit around the actual release time per class (time.yaml)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from capitalizator.news_macro.ingest import NewsIngest, default_macro_path
from capitalizator.news_macro.rules import MacroRules
from capitalizator.risk.session import load_time_config


def _rows():
    return NewsIngest.from_csv(default_macro_path()).rows


def test_windows_loaded_with_provenance_for_every_us_class() -> None:
    cfg = load_time_config()
    assert set(cfg["event_windows"]) == {"CPI", "NFP", "PCE", "FOMC"}
    rules = MacroRules(enabled=True)
    assert rules.event_windows["CPI"] == (timedelta(minutes=30), timedelta(minutes=60))
    assert rules.event_windows["FOMC"] == (timedelta(minutes=30), timedelta(minutes=90))


def test_nfp_release_is_closed_and_edges_are_open() -> None:
    rows = _rows()
    rules = MacroRules(enabled=True)
    release = datetime(2026, 9, 4, 12, 30, tzinfo=UTC)  # NFP Aug 2026, 08:30 EDT
    assert rules.decide(release, rows).reason == "event_window_NFP"
    assert rules.decide(release - timedelta(minutes=30), rows).allow is False
    assert rules.decide(release - timedelta(minutes=31), rows).allow is True
    assert rules.decide(release + timedelta(minutes=60), rows).allow is False
    assert rules.decide(release + timedelta(minutes=61), rows).allow is True


def test_fomc_statement_window_covers_presser_and_legacy_reason_kept() -> None:
    rows = _rows()
    rules = MacroRules(enabled=True)
    statement = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)  # 14:00 EDT
    # 14:00–15:00 ET keeps the legacy reason string; the window covers 13:30–15:30 ET
    assert rules.decide(statement + timedelta(minutes=10), rows).reason == "et_blackout"
    assert rules.decide(statement - timedelta(minutes=20), rows).reason == "event_window_FOMC"
    assert rules.decide(statement + timedelta(minutes=80), rows).reason == "event_window_FOMC"
    assert rules.decide(statement + timedelta(minutes=91), rows).allow is True


def test_unknown_row_is_not_a_window() -> None:
    """known_at in the future → the desk does not know about the event yet."""
    rows = _rows()
    rules = MacroRules(enabled=True)
    before_known = datetime(2026, 8, 30, 12, 30, tzinfo=UTC)
    assert rules._event_window(before_known, rows) is None

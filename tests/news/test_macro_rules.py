"""2.11.7 — 24h pre CPI/FOMC from time.yaml. Session does not apply this."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.news_macro.ingest import NewsIngest
from capitalizator.news_macro.rules import MacroRules
from capitalizator.risk.session import SessionWindow

MACRO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "macro.csv"


def test_disabled_does_not_cut() -> None:
    news = NewsIngest.from_csv(MACRO)
    got = MacroRules(enabled=False).decide(
        datetime(2026, 9, 10, 14, 10, tzinfo=UTC), news.rows
    )
    assert got.reason == "macro_off"
    assert got.size_mult == Decimal("1")
    assert got.allow is True


def test_day_before_cpi_is_pre_event_when_enabled() -> None:
    news = NewsIngest.from_csv(MACRO)
    when = datetime(2026, 9, 10, 14, 10, tzinfo=UTC)
    win_ok, win_reason = SessionWindow().allows(when, news.rows)
    assert win_ok is True
    assert win_reason == "session"
    got = MacroRules(enabled=True).decide(when, news.rows)
    assert got.reason == "pre_event"
    assert got.size_mult == Decimal("0.5")
    assert got.allow is True


def test_two_days_before_cpi_is_ok() -> None:
    news = NewsIngest.from_csv(MACRO)
    got = MacroRules(enabled=True).decide(
        datetime(2026, 9, 9, 14, 10, tzinfo=UTC), news.rows
    )
    assert got.reason == "ok"
    assert got.size_mult == Decimal("1")


def test_fomc_blackout_et_is_closed() -> None:
    """16 Sep 2026 FOMC 18:00Z = 14:00 EDT. Blackout 14:00–15:00 ET."""
    news = NewsIngest.from_csv(MACRO)
    got = MacroRules(enabled=True).decide(
        datetime(2026, 9, 16, 18, 10, tzinfo=UTC), news.rows
    )
    assert got.allow is False
    assert got.reason == "fomc_blackout"
    assert got.size_mult == Decimal("0")

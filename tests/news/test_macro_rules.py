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
    assert got.reason == "et_blackout"
    assert got.size_mult == Decimal("0")


def test_cpi_day_et_hour_is_closed() -> None:
    """11 Sep 2026 18:10Z = 14:10 EDT on a CPI day."""
    news = NewsIngest.from_csv(MACRO)
    got = MacroRules(enabled=True).decide(
        datetime(2026, 9, 11, 18, 10, tzinfo=UTC), news.rows
    )
    assert got.allow is False
    assert got.reason == "et_blackout"


def test_december_fomc_est_blackout_is_1900z() -> None:
    """9 Dec 2026 is EST. 14:10 ET = 19:10Z. 18:10Z is still 13:10 ET — not the hour."""
    news = NewsIngest.from_csv(MACRO)
    rules = MacroRules(enabled=True)
    early = rules.decide(datetime(2026, 12, 9, 18, 10, tzinfo=UTC), news.rows)
    assert early.allow is True
    assert early.reason == "pre_event"
    late = rules.decide(datetime(2026, 12, 9, 19, 10, tzinfo=UTC), news.rows)
    assert late.allow is False
    assert late.reason == "et_blackout"

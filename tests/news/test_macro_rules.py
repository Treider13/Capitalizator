"""2.11.7 — 24h pre CPI/FOMC from time.yaml. Session does not apply this."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.news_macro.ingest import NewsIngest
from capitalizator.news_macro.rules import PRE_CLASSES, MacroRules
from capitalizator.risk.sessions import SessionPolicy

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
    win_ok, win_reason = SessionPolicy.load().allows(when, news.rows, idea="bounce", symbol="BTCUSDT")
    assert win_ok is True
    assert win_reason.startswith("window:")
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
    """D-22: CPI prints 08:30 ET (12:30Z on 11 Sep 2026). The release window
    closes 12:00Z–13:30Z; 14:10 EDT (18:10Z) on a CPI day is an ordinary hour —
    the old 14:00–15:00 ET blackout matched nothing real for CPI."""
    news = NewsIngest.from_csv(MACRO)
    rules = MacroRules(enabled=True)
    inside = rules.decide(datetime(2026, 9, 11, 12, 45, tzinfo=UTC), news.rows)
    assert inside.allow is False
    assert inside.reason == "event_window_CPI"
    before = rules.decide(datetime(2026, 9, 11, 11, 59, tzinfo=UTC), news.rows)
    assert before.allow is True  # still >24h? no: pre_event cut applies, but not closed
    after = rules.decide(datetime(2026, 9, 11, 13, 31, tzinfo=UTC), news.rows)
    assert after.allow is True
    afternoon = rules.decide(datetime(2026, 9, 11, 18, 10, tzinfo=UTC), news.rows)
    assert afternoon.allow is True
    assert afternoon.reason == "ok"


def test_nfp_is_not_pre_event_or_et_blackout() -> None:
    """NFP/PCE close the morning via the session policy. MacroRules 24h/ET stay CPI+FOMC."""
    assert PRE_CLASSES == frozenset({"CPI", "FOMC"})
    news = NewsIngest.from_csv(MACRO)
    rules = MacroRules(enabled=True)
    day_before = rules.decide(datetime(2026, 9, 3, 14, 10, tzinfo=UTC), news.rows)
    assert day_before.reason == "ok"
    assert day_before.size_mult == Decimal("1")
    nfp_et = rules.decide(datetime(2026, 9, 4, 18, 10, tzinfo=UTC), news.rows)
    assert nfp_et.allow is True
    assert nfp_et.reason == "ok"


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

"""3.13.4 — wick beyond + close inside is failed_break. Not a breakout entry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.failed_break import TAG, FailedBreak
from capitalizator.zones.model import Bar, Zone

CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CLOSE = datetime(2026, 8, 31, 13, 45, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec"


def _zone(*, side: str = "support") -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side=side,  # type: ignore[arg-type]
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )


def _bar(*, low: str, high: str, close: str) -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=CLOSE - timedelta(minutes=15),
        close_ts=CLOSE,
        open=Decimal("100.5"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_wick_below_support_close_inside_is_failed_break() -> None:
    assert FailedBreak.tag(zone=_zone(), bar=_bar(low="99.5", high="100.8", close="100.4")) == TAG


def test_close_beyond_support_is_not_failed_break() -> None:
    assert FailedBreak.tag(zone=_zone(), bar=_bar(low="99.5", high="100.8", close="99.8")) is None


def test_no_wick_inside_is_not_failed_break() -> None:
    assert FailedBreak.tag(zone=_zone(), bar=_bar(low="100.2", high="100.8", close="100.4")) is None


def test_wick_above_resistance_close_inside_is_failed_break() -> None:
    zone = _zone(side="resistance")
    assert FailedBreak.tag(zone=zone, bar=_bar(low="100.1", high="101.8", close="100.6")) == TAG


def test_tag_does_not_count_as_breakout_or_bounce() -> None:
    assert FailedBreak.counts_as_breakout(TAG) is False
    assert FailedBreak.counts_as_bounce(TAG) is False


def test_bounce_source_does_not_import_failed_break() -> None:
    text = (SRC / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "FailedBreak" not in text
    assert "failed_break" not in text
    assert 'SETUP_TAG = "bounce"' in text

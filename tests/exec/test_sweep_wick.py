"""sweep_wick shares FailedBreak's wick atom. Close-through is still a sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.exec.failed_break import TAG, FailedBreak, sweep_wick, wick_beyond
from capitalizator.zones.model import Bar, Zone

CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CLOSE = datetime(2026, 8, 31, 13, 45, tzinfo=UTC)


def _zone() -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
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


def test_failed_break_wick_is_sweep() -> None:
    zone = _zone()
    bar = _bar(low="99.5", high="100.8", close="100.4")
    assert wick_beyond(zone=zone, bar=bar) is True
    assert sweep_wick(zone=zone, bar=bar) is True
    assert FailedBreak.tag(zone=zone, bar=bar) == TAG


def test_close_through_is_sweep_not_failed_break() -> None:
    zone = _zone()
    bar = _bar(low="99.5", high="100.8", close="99.8")
    assert sweep_wick(zone=zone, bar=bar) is True
    assert FailedBreak.tag(zone=zone, bar=bar) is None


def test_inside_bar_is_not_sweep() -> None:
    zone = _zone()
    bar = _bar(low="100.2", high="100.8", close="100.4")
    assert sweep_wick(zone=zone, bar=bar) is False

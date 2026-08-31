"""2.9.2 — wick through support is not a break. Close + eaten is."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.btc.break_def import Break
from capitalizator.zones.model import Bar, Zone

CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CLOSE = datetime(2026, 8, 31, 13, 45, tzinfo=UTC)
T = CLOSE + timedelta(seconds=1)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _bar(*, low: str, close: str, close_ts: datetime = CLOSE, symbol: str = "BTCUSDT") -> Bar:
    return Bar(
        symbol=symbol,
        tf="15m",
        open_ts=close_ts - timedelta(minutes=15),
        close_ts=close_ts,
        open=Decimal("100.1"),
        high=Decimal("100.3"),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_wick_below_support_without_close_is_not_break() -> None:
    bar = _bar(low="99.5", close="100.1")
    assert Break.detect(zone=ZONE, bar=bar, tape_eaten=True, t=T) is False


def test_close_beyond_without_eaten_is_not_break() -> None:
    bar = _bar(low="99.5", close="99.8")
    assert Break.detect(zone=ZONE, bar=bar, tape_eaten=False, t=T) is False


def test_close_beyond_and_eaten_is_break() -> None:
    bar = _bar(low="99.5", close="99.8")
    assert Break.detect(zone=ZONE, bar=bar, tape_eaten=True, t=T) is True


def test_unclosed_bar_is_not_break() -> None:
    bar = _bar(low="99.5", close="99.8")
    assert Break.detect(zone=ZONE, bar=bar, tape_eaten=True, t=CLOSE) is False


def test_wick_above_resistance_without_close_is_not_break() -> None:
    resist = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=CLOSE - timedelta(minutes=15),
        close_ts=CLOSE,
        open=Decimal("100.1"),
        high=Decimal("100.8"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
    )
    assert Break.detect(zone=resist, bar=bar, tape_eaten=True, t=T) is False


def test_close_above_resistance_and_eaten_is_break() -> None:
    resist = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=CLOSE - timedelta(minutes=15),
        close_ts=CLOSE,
        open=Decimal("100.1"),
        high=Decimal("100.8"),
        low=Decimal("100.0"),
        close=Decimal("100.5"),
    )
    assert Break.detect(zone=resist, bar=bar, tape_eaten=True, t=T) is True


def test_eth_zone_is_not_a_btc_break() -> None:
    eth = Zone.create(
        symbol="ETHUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    bar = _bar(low="99.5", close="99.8", symbol="ETHUSDT")
    assert Break.detect(zone=eth, bar=bar, tape_eaten=True, t=T) is False

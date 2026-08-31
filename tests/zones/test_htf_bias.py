"""0.3.2 — HTF bias from closed 4h bars. Future bar does not flip the side."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.zones.map import ZoneMap
from capitalizator.zones.model import Bar


def _h4(hour: int, high: str, low: str, close: str) -> Bar:
    open_ts = datetime(2026, 8, 30, hour, tzinfo=UTC)
    return Bar(
        symbol="BTCUSDT",
        tf="4h",
        open_ts=open_ts,
        close_ts=datetime(2026, 8, 30, hour + 4, tzinfo=UTC),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_three_bars_break_up_is_long() -> None:
    bars = [
        _h4(0, "10", "8", "9"),
        _h4(4, "11", "8", "10"),
        _h4(8, "20", "12", "19"),
    ]
    t = datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC)
    assert ZoneMap().htf_bias("BTCUSDT", t, bars) == "long"


def test_future_bar_does_not_change_bias() -> None:
    bars = [
        _h4(0, "10", "8", "9"),
        _h4(4, "11", "8", "10"),
        _h4(8, "20", "12", "19"),
        _h4(12, "5", "1", "2"),
    ]
    t = datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC)
    assert ZoneMap().htf_bias("BTCUSDT", t, bars) == "long"
    later = datetime(2026, 8, 30, 16, 0, 1, tzinfo=UTC)
    assert ZoneMap().htf_bias("BTCUSDT", later, bars) == "short"


def test_not_enough_bars_is_unknown() -> None:
    bars = [_h4(0, "10", "8", "9")]
    t = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    assert ZoneMap().htf_bias("BTCUSDT", t, bars) == "unknown"

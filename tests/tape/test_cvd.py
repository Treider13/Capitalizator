"""CVD is signed tape in the same window as the touch. Not a 5-minute signal. No size."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.tape.cvd import CVD
from capitalizator.types import MarketEvent

TS = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _trade(side: str, qty: str = "1") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=TS,
        recv_ts=TS,
        payload={"px": "100", "qty": qty, "side": side},
    )


def test_buy_minus_sell() -> None:
    assert CVD().window([_trade("buy", "2"), _trade("sell", "5")]) == Decimal("-3")


def test_empty_window_is_zero() -> None:
    assert CVD().window([]) == Decimal("0")


def test_unknown_side_is_error() -> None:
    with pytest.raises(ValueError, match="taker"):
        CVD().window([_trade("maker")])


def test_non_trade_is_skipped() -> None:
    gap = MarketEvent(
        stream="gap",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=TS,
        recv_ts=TS,
        payload={},
    )
    assert CVD().window([gap, _trade("buy", "4")]) == Decimal("4")

"""Taker side is the print. We do not guess it."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent

TS = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _trade(side: str) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=TS,
        recv_ts=TS,
        seq=None,
        payload={"px": "1", "qty": "0.001", "side": side},
    )


def test_buy_and_sell() -> None:
    clf = TapeClassifier()
    assert clf.taker_side(_trade("buy")) == "buy"
    assert clf.taker_side(_trade("sell")) == "sell"


def test_unknown_side_rejected() -> None:
    with pytest.raises(ValueError, match="unknown taker"):
        TapeClassifier().taker_side(_trade("maker"))

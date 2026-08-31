"""p50/p95 of recv-exchange lag. Nearest-rank. Empty list is an error."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from capitalizator.ops.latency import lag_report, percentile
from capitalizator.types import MarketEvent


def test_nearest_rank_on_one_to_one_hundred() -> None:
    values = [float(i) for i in range(1, 101)]
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95


def test_lag_report_on_known_offsets() -> None:
    base = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    events = [
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=base,
            recv_ts=base + timedelta(milliseconds=i),
            seq=None,
            payload={"px": "1", "qty": "0.001", "side": "buy"},
        )
        for i in range(1, 101)
    ]
    report = lag_report(events)
    assert report["n"] == 100
    assert report["p50_ms"] == 50
    assert report["p95_ms"] == 95


def test_empty_is_error() -> None:
    with pytest.raises(ValueError, match="no events"):
        lag_report([])

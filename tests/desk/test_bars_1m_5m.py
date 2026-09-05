"""1m/5m buckets exist for features. Zones still refuse them as working_tf."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from capitalizator.desk.bars import TF_MINUTES, BarBuilder, closed_bars_from_trades
from capitalizator.types import MarketEvent
from capitalizator.zones.config import KNOWN_TFS, load_registry

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _trade(ts: datetime, px: str) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "1", "side": "buy"},
    )


def test_tf_minutes_has_one_and_five() -> None:
    assert TF_MINUTES["1m"] == 1
    assert TF_MINUTES["5m"] == 5
    assert "3m" not in TF_MINUTES


def test_five_minute_builder_matches_rescan() -> None:
    trades = [_trade(T0 + timedelta(seconds=30 * i), str(100 + i)) for i in range(20)]
    now = T0 + timedelta(minutes=11)
    expected = closed_bars_from_trades(
        trades, symbol="BTCUSDT", tf="5m", now=now, already=set()
    )
    builder = BarBuilder(symbol="BTCUSDT", tfs=("5m",))
    got = []
    for trade in trades:
        got.extend(builder.close_due(trade.exchange_ts))
        builder.on_trade(trade)
    got.extend(builder.close_due(now))
    assert got == expected
    assert len(got) == 2  # 10:00 and 10:05 close before 10:11


def test_three_minute_still_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        BarBuilder(symbol="BTCUSDT", tfs=("3m",))


def test_zone_known_tfs_do_not_include_feature_buckets() -> None:
    assert "1m" not in KNOWN_TFS
    assert "5m" not in KNOWN_TFS
    # Frozen registry still loads as 15m working.
    cfg = load_registry()
    assert cfg.working_tf == "15m"

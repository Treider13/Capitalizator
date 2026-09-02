"""BarBuilder == closed_bars_from_trades on the same prints; O(1) per print; no loss."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.desk.bars import BarBuilder, closed_bars_from_trades
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _trade(ts: datetime, px: str, qty: str = "1", symbol: str = "BTCUSDT") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": qty, "side": "buy"},
    )


def _tape(n: int, step_s: int = 30) -> list[MarketEvent]:
    out = []
    px = Decimal("100")
    for i in range(n):
        px += Decimal("0.1") if i % 3 else Decimal("-0.2")
        out.append(_trade(T0 + timedelta(seconds=i * step_s), str(px), str(1 + i % 4)))
    return out


def test_builder_matches_rescan_bit_for_bit() -> None:
    trades = _tape(400)  # 200 minutes → 13 closed 15m bars, 0 closed 4h
    now = trades[-1].exchange_ts + timedelta(seconds=1)
    expected = closed_bars_from_trades(trades, symbol="BTCUSDT", tf="15m", now=now, already=set())
    builder = BarBuilder(symbol="BTCUSDT", tfs=("15m", "4h", "1d"))
    got = []
    for trade in trades:
        got.extend(builder.close_due(trade.exchange_ts))
        builder.on_trade(trade)
    got.extend(builder.close_due(now))
    got15 = [b for b in got if b.tf == "15m"]
    assert len(expected) == 13
    assert got15 == expected
    assert builder.late_prints == 0


def test_next_bucket_print_parks_previous_bar_nothing_lost() -> None:
    builder = BarBuilder(symbol="BTCUSDT", tfs=("15m",))
    builder.on_trade(_trade(T0 + timedelta(minutes=1), "100"))
    builder.on_trade(_trade(T0 + timedelta(minutes=16), "101"))  # no close_due in between
    bars = builder.close_due(T0 + timedelta(minutes=16))
    assert [b.close for b in bars] == [Decimal("100")]
    assert builder.open_bucket("15m") is not None
    assert builder.open_bucket("15m").close == Decimal("101")


def test_late_print_never_rewrites_closed_bar() -> None:
    builder = BarBuilder(symbol="BTCUSDT", tfs=("15m",))
    builder.on_trade(_trade(T0 + timedelta(minutes=1), "100"))
    closed = builder.close_due(T0 + timedelta(minutes=15))
    assert len(closed) == 1
    builder.on_trade(_trade(T0 + timedelta(minutes=2), "50"))  # arrives late
    assert builder.late_prints == 1
    assert builder.close_due(T0 + timedelta(minutes=30)) == []


def test_seeded_bars_are_not_reopened() -> None:
    builder = BarBuilder(symbol="BTCUSDT", tfs=("15m",))
    seeded = closed_bars_from_trades(
        [_trade(T0 + timedelta(minutes=3), "100")],
        symbol="BTCUSDT",
        tf="15m",
        now=T0 + timedelta(minutes=15),
        already=set(),
    )
    builder.seed_closed(seeded)
    builder.on_trade(_trade(T0 + timedelta(minutes=5), "99"))
    assert builder.late_prints == 1
    assert builder.close_due(T0 + timedelta(minutes=15)) == []


def test_other_symbol_ignored_and_bad_payload_skipped() -> None:
    builder = BarBuilder(symbol="BTCUSDT", tfs=("15m",))
    builder.on_trade(_trade(T0, "100", symbol="ETHUSDT"))
    bad = _trade(T0, "100")
    bad.payload["px"] = "not-a-number"
    builder.on_trade(bad)
    assert builder.close_due(T0 + timedelta(hours=1)) == []


def test_bad_tf_rejected() -> None:
    try:
        BarBuilder(symbol="BTCUSDT", tfs=("3m",))
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("3m must be rejected")

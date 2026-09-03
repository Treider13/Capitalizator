"""F0 uptime tracked incrementally: the law the console evaluates without the tape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from capitalizator.ops.uptime import MAX_UNMARKED_GAP_S, UptimeTracker, hours24_from_state
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _trade(ts: datetime, symbol: str = "BTCUSDT") -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol=symbol, exchange_ts=ts, recv_ts=ts,
                       seq=None, payload={"px": "1", "qty": "1", "side": "buy"})


def _gap(lo: datetime, hi: datetime, symbol: str = "BTCUSDT") -> MarketEvent:
    return MarketEvent(stream="gap", exchange="bybit", symbol=symbol, exchange_ts=lo, recv_ts=hi,
                       seq=None, payload={"ts_from": lo.isoformat(), "ts_to": hi.isoformat()})


def _state(tr: UptimeTracker) -> dict:
    import json

    return json.loads(tr.to_json())


def test_market_pauses_under_a_minute_are_not_holes() -> None:
    tr = UptimeTracker()
    t = T0
    for _ in range(3000):  # 30 s apart → 25 h
        tr.on_event(_trade(t))
        t += timedelta(seconds=30)
    ok, span, detail = hours24_from_state(_state(tr), symbol="BTCUSDT")
    assert ok and span >= 24 * 3600 and detail["unmarked_holes"] == 0


def test_unmarked_hole_breaks_the_stretch_and_a_marker_heals_it() -> None:
    tr = UptimeTracker()
    tr.on_event(_trade(T0))
    mid = T0 + timedelta(hours=12)
    tr.on_event(_trade(mid))  # 12 h silence, nobody marked it
    end = T0 + timedelta(hours=25)
    tr.on_event(_trade(end - timedelta(hours=12)))
    tr.on_event(_trade(end))
    ok, span, detail = hours24_from_state(_state(tr), symbol="BTCUSDT")
    assert not ok and detail["unmarked_holes"] >= 1
    # the recorder's marker for exactly that hole arrives (file order): the stretch is whole
    tr2 = UptimeTracker()
    tr2.on_event(_trade(T0))
    tr2.on_event(_trade(mid))
    tr2.on_event(_gap(T0, mid))
    tr2.on_event(_gap(mid, end))  # and the second hole is marked before its print
    tr2.on_event(_trade(end))
    ok, span, _ = hours24_from_state(_state(tr2), symbol="BTCUSDT")
    assert ok and span == 25 * 3600


def test_eth_marker_does_not_green_btc_and_state_roundtrips() -> None:
    tr = UptimeTracker()
    tr.on_event(_trade(T0))
    tr.on_event(_gap(T0, T0 + timedelta(hours=25), symbol="ETHUSDT"))
    tr.on_event(_trade(T0 + timedelta(hours=25)))
    ok, _, _ = hours24_from_state(_state(tr), symbol="BTCUSDT")
    assert not ok
    again = UptimeTracker.from_json(tr.to_json())
    assert again.to_json() == tr.to_json()
    assert MAX_UNMARKED_GAP_S == 60.0

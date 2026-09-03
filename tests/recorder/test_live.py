"""Live runner: injected frames, ticker→funding/OI, multiplex subscribe."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.recorder.app import RecorderApp
from capitalizator.recorder.live import run_live, subscribe_desk, ticker_events
from capitalizator.recorder.public_ws import subscribe_many
from capitalizator.screener.universe import load_desk_universe
from capitalizator.types import MarketEvent

NOW = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)


def test_empty_live_is_recording(tmp_path: Path) -> None:
    app = RecorderApp()
    n = run_live(app, minutes=1, symbol="BTCUSDT", data_root=tmp_path)
    assert n == 0
    assert app.recording is True


def test_injected_events_write(tmp_path: Path) -> None:
    app = RecorderApp()
    event = MarketEvent(
        stream="funding",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=NOW,
        recv_ts=NOW,
        payload={"funding": "0.01"},
    )
    n = run_live(app, minutes=1, symbol="BTCUSDT", data_root=tmp_path, events=[event])
    assert n == 1


def test_ticker_frame_splits_funding_and_oi() -> None:
    events = ticker_events(
        {
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "fundingRate": "0.0001",
                "openInterest": "12",
                "ts": 1725024600000,
            },
        },
        recv_ts=NOW,
    )
    streams = {e.stream for e in events}
    assert streams == {"funding", "oi"}


def test_ticker_frame_emits_mark() -> None:
    events = ticker_events(
        {
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "markPrice": "65000.1",
                "ts": 1725024600000,
            },
        },
        recv_ts=NOW,
    )
    assert [e.stream for e in events] == ["mark"]
    assert events[0].payload["mark"] == "65000.1"


def test_fetch_ticker_writes_rest_events(tmp_path: Path) -> None:
    app = RecorderApp()
    rest = [
        MarketEvent(
            stream="mark",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"mark": "1"},
        )
    ]
    n = run_live(
        app,
        minutes=1,
        symbol="BTCUSDT",
        data_root=tmp_path,
        fetch_ticker=lambda: rest,
    )
    assert n == 1


def test_subscribe_many_covers_desk_universe() -> None:
    uni = load_desk_universe()
    payload = subscribe_desk(uni.symbols)
    assert payload["op"] == "subscribe"
    assert len(payload["args"]) == 24 * 5
    assert "allLiquidation.BTCUSDT" in payload["args"]
    one = subscribe_many(["BTCUSDT"], ["trades", "book"])
    assert "publicTrade.BTCUSDT" in one["args"]
    assert "orderbook.200.BTCUSDT" in one["args"]


def test_liquidation_frame_keeps_position_side() -> None:
    """Official: S=Buy means a *long* was liquidated. We store position, not a taker."""
    from capitalizator.recorder.live import liquidation_events

    events = liquidation_events(
        {
            "topic": "allLiquidation.ROSEUSDT",
            "type": "snapshot",
            "ts": 1739502303204,
            "data": [{"T": 1739502302929, "s": "ROSEUSDT", "S": "Sell", "v": "20000", "p": "0.04499"}],
        },
        recv_ts=NOW,
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.stream == "liquidation"
    assert ev.symbol == "ROSEUSDT"
    assert ev.payload == {"px": "0.04499", "qty": "20000", "position": "short"}
    assert ev.exchange_ts.isoformat() == "2025-02-14T03:05:02.929000+00:00"
    long_side = liquidation_events(
        {"topic": "allLiquidation.BTCUSDT", "data": [{"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "2"}]},
        recv_ts=NOW,
    )
    assert long_side[0].payload["position"] == "long"
    assert liquidation_events({"op": "subscribe", "success": True}, recv_ts=NOW) == []
    import pytest

    with pytest.raises(ValueError, match="missing"):
        liquidation_events({"topic": "allLiquidation.X", "data": [{"T": 1, "s": "X"}]}, recv_ts=NOW)
    with pytest.raises(ValueError, match="side"):
        liquidation_events({"topic": "allLiquidation.X", "data": [{"T": 1, "s": "X", "S": "Long", "v": "1", "p": "1"}]}, recv_ts=NOW)


def test_run_live_writes_liquidation_frames(tmp_path: Path) -> None:
    app = RecorderApp()
    frame = {
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1739502303204,
        "data": [{"T": 1739502302929, "s": "BTCUSDT", "S": "Buy", "v": "0.5", "p": "60000"}],
    }
    n = run_live(app, minutes=1, symbol="BTCUSDT", data_root=tmp_path, stream="liquidation", frames=[frame])
    assert n == 1
    payload = subscribe_many(["BTCUSDT"], ["liquidation"])
    assert payload["args"] == ["allLiquidation.BTCUSDT"]

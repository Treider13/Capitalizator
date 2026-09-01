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


def test_subscribe_many_covers_desk_universe() -> None:
    uni = load_desk_universe()
    payload = subscribe_desk(uni.symbols)
    assert payload["op"] == "subscribe"
    assert len(payload["args"]) == 24 * 4
    one = subscribe_many(["BTCUSDT"], ["trades", "book"])
    assert "publicTrade.BTCUSDT" in one["args"]
    assert "orderbook.200.BTCUSDT" in one["args"]

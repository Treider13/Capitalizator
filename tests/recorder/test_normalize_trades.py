"""0.1.4: 100 mock trades → 100 MarketEvents. No live socket."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.recorder.ws_trades import BybitTradesWs

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_trades_100.jsonl"


def test_one_hundred_trades_normalize() -> None:
    lines = FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    normalizer = TradesNormalizer()
    events = []
    for i, line in enumerate(lines, start=1):
        events.append(normalizer.normalize(json.loads(line), recv_ts=recv, seq=i))
    assert len(events) == 100
    assert all(e.stream == "trades" for e in events)
    assert all(e.symbol == "BTCUSDT" for e in events)
    assert all(e.payload["side"] in {"buy", "sell"} for e in events)
    assert [e.seq for e in events] == list(range(1, 101))


def test_bad_payload_rejected() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        TradesNormalizer().normalize({"foo": 1}, recv_ts=recv)


def test_missing_price_is_value_error_not_keyerror() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    raw = {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0.001"}
    with pytest.raises(ValueError, match="missing"):
        TradesNormalizer().normalize(raw, recv_ts=recv)


def test_ws_frame_unwraps_data_array() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    frame = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"T": 1725024600000, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "65000.0", "i": "a"},
            {"T": 1725024600200, "s": "BTCUSDT", "S": "Sell", "v": "0.002", "p": "65001.0", "i": "b"},
        ],
    }
    events = TradesNormalizer().normalize_frame(frame, recv_ts=recv, seq_start=10)
    assert len(events) == 2
    assert [e.seq for e in events] == [10, 11]
    assert events[0].payload["side"] == "buy"
    assert events[1].payload["side"] == "sell"


def test_ws_ingest_assigns_monotonic_seq() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    frames = [
        {
            "topic": "publicTrade.BTCUSDT",
            "data": [
                {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "1", "i": "a"},
            ],
        },
        {
            "topic": "publicTrade.BTCUSDT",
            "data": [
                {"T": 2, "s": "BTCUSDT", "S": "Sell", "v": "0.001", "p": "2", "i": "b"},
            ],
        },
    ]
    events = BybitTradesWs().ingest_frames(frames, recv_ts=recv)
    assert [e.seq for e in events] == [1, 2]

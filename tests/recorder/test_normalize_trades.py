"""0.1.4: 100 mock trades → 100 MarketEvents. Seq is Bybit's, or None."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.recorder.gap import GapDetector, SeqFault
from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.recorder.ws_trades import BybitTradesWs

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_trades_100.jsonl"

# https://bybit-exchange.github.io/docs/v5/websocket/public/trade
OFFICIAL_TRADE_FRAME = {
    "topic": "publicTrade.BTCUSDT",
    "type": "snapshot",
    "ts": 1672304486868,
    "data": [
        {
            "T": 1672304486865,
            "s": "BTCUSDT",
            "S": "Buy",
            "v": "0.001",
            "p": "16578.50",
            "L": "PlusTick",
            "i": "20f43950-d8dd-5b31-9112-a178eb6023af",
            "BT": False,
            "seq": 1783284617,
        }
    ],
}


def test_one_hundred_trades_normalize() -> None:
    lines = FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    events = [TradesNormalizer().normalize(json.loads(line), recv_ts=recv) for line in lines]
    assert len(events) == 100
    assert all(e.stream == "trades" for e in events)
    assert all(e.symbol == "BTCUSDT" for e in events)
    assert all(e.payload["side"] in {"buy", "sell"} for e in events)
    # fixture has no Bybit seq — we must not invent 1..100
    assert all(e.seq is None for e in events)


def test_official_public_trade_example() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    events = TradesNormalizer().normalize_frame(OFFICIAL_TRADE_FRAME, recv_ts=recv)
    assert len(events) == 1
    ev = events[0]
    assert ev.seq == 1783284617
    assert ev.payload["cross_seq"] == 1783284617
    assert ev.payload["px"]
    assert ev.payload["side"] == "buy"
    assert ev.exchange_ts == datetime.fromtimestamp(1672304486865 / 1000, tz=UTC)


def test_same_cross_seq_on_two_messages_is_legal() -> None:
    """Bybit: several messages may share one seq. GapDetector must not run on it."""
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    frame_a = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "1", "i": "a", "seq": 99},
        ],
    }
    frame_b = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"T": 2, "s": "BTCUSDT", "S": "Sell", "v": "0.001", "p": "2", "i": "b", "seq": 99},
        ],
    }
    events = BybitTradesWs().ingest_frames([frame_a, frame_b], recv_ts=recv)
    assert [e.seq for e in events] == [99, 99]
    with pytest.raises(SeqFault):
        GapDetector().on_seq(99, 99)


def test_bad_payload_rejected() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        TradesNormalizer().normalize({"foo": 1}, recv_ts=recv)


def test_missing_price_is_value_error_not_keyerror() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    raw = {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0.001"}
    with pytest.raises(ValueError, match="missing"):
        TradesNormalizer().normalize(raw, recv_ts=recv)


def test_empty_data_array_is_zero_events() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    assert TradesNormalizer().normalize_frame(
        {"topic": "publicTrade.BTCUSDT", "data": []}, recv_ts=recv
    ) == []


def test_zero_qty_rejected() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    raw = {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0", "p": "1"}
    with pytest.raises(ValueError, match="px/qty"):
        TradesNormalizer().normalize(raw, recv_ts=recv)


def test_ws_frame_unwraps_data_array() -> None:
    recv = datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC)
    frame = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {
                "T": 1725024600000,
                "s": "BTCUSDT",
                "S": "Buy",
                "v": "0.001",
                "p": "65000.0",
                "i": "a",
                "seq": 10,
            },
            {
                "T": 1725024600200,
                "s": "BTCUSDT",
                "S": "Sell",
                "v": "0.002",
                "p": "65001.0",
                "i": "b",
                "seq": 10,
            },
        ],
    }
    events = TradesNormalizer().normalize_frame(frame, recv_ts=recv)
    assert len(events) == 2
    assert [e.seq for e in events] == [10, 10]
    assert events[0].payload["side"] == "buy"
    assert events[1].payload["side"] == "sell"

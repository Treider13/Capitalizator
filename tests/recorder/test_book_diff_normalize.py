"""0.2.2 — WS book frames. Official shape + fixture snapshot+20 diffs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.recorder.book_diff import BookDiffNormalizer
from capitalizator.recorder.ws_book import BybitBookWs

# https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
OFFICIAL_WS_SNAPSHOT = {
    "topic": "orderbook.50.BTCUSDT",
    "type": "snapshot",
    "ts": 1672304484978,
    "data": {
        "s": "BTCUSDT",
        "b": [["16493.50", "0.006"], ["16493.00", "0.100"]],
        "a": [["16611.00", "0.029"], ["16612.00", "0.213"]],
        "u": 18521288,
        "seq": 7961638724,
    },
    "cts": 1672304484976,
}

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_book_snapshot_20_diffs.jsonl"


def test_parse_official_ws_snapshot() -> None:
    kind, snap = BookDiffNormalizer().parse_frame(OFFICIAL_WS_SNAPSHOT)
    assert kind == "snapshot"
    assert snap.seq == 18521288
    assert snap.cross_seq == 7961638724
    assert snap.symbol == "BTCUSDT"
    assert snap.bids[0] == ("16493.50", "0.006")


def test_parse_delta_empty_side() -> None:
    frame = {
        "topic": "orderbook.200.BTCUSDT",
        "type": "delta",
        "ts": 1672304485000,
        "data": {"s": "BTCUSDT", "u": 18521289, "seq": 7961638725, "b": [["16493.50", "0"]], "a": []},
    }
    kind, snap = BookDiffNormalizer().parse_frame(frame)
    assert kind == "delta"
    assert snap.bids == (("16493.50", "0"),)
    assert snap.asks == ()


def test_unknown_type_is_error() -> None:
    with pytest.raises(ValueError, match="unknown book type"):
        BookDiffNormalizer().parse_frame({"type": "trade", "ts": 1, "data": {"s": "X", "u": 1}})


def test_missing_u_is_error() -> None:
    with pytest.raises(ValueError, match="missing u"):
        BookDiffNormalizer().parse_frame(
            {"type": "delta", "ts": 1, "data": {"s": "BTCUSDT", "seq": 9, "b": [], "a": []}}
        )


def test_to_event_streams() -> None:
    recv = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    kind, snap = BookDiffNormalizer().parse_frame(OFFICIAL_WS_SNAPSHOT)
    event = BookDiffNormalizer().to_event(kind, snap, recv_ts=recv)
    assert event.stream == "snapshot"
    assert event.seq == 18521288


def test_fixture_snapshot_plus_twenty_diffs() -> None:
    lines = FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 21
    frames = [json.loads(line) for line in lines]
    assert frames[0]["type"] == "snapshot"
    assert [f["type"] for f in frames[1:]] == ["delta"] * 20
    us = [f["data"]["u"] for f in frames]
    assert us == list(range(100, 121))
    recv = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    events = BybitBookWs().ingest_frames(frames, recv_ts=recv)
    diffs = [e for e in events if e.stream == "book_diff"]
    snaps = [e for e in events if e.stream == "snapshot"]
    bbos = [e for e in events if e.stream == "bbo"]
    assert len(snaps) == 1
    assert len(diffs) == 20
    assert len(bbos) == 21
    assert [e.seq for e in snaps + diffs] == list(range(100, 121))

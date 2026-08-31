"""0.1.4: 100 mock trades → 100 MarketEvents. No live socket."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.recorder.normalize import TradesNormalizer

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
    try:
        TradesNormalizer().normalize({"foo": 1}, recv_ts=recv)
    except ValueError:
        return
    raise AssertionError("expected ValueError")

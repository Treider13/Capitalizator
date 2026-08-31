"""0.1.6: seq 5 → 8 is exactly one gap covering 6–7."""

from __future__ import annotations

from datetime import UTC, datetime

from capitalizator.recorder.gap import GapDetector


def test_seq_skip_5_to_8() -> None:
    detector = GapDetector()
    gap = detector.on_seq(5, 8)
    assert gap is not None
    assert gap.seq_from == 6
    assert gap.seq_to == 7
    event = detector.event(
        gap,
        symbol="BTCUSDT",
        stream="trades",
        exchange="bybit",
        exchange_ts=datetime(2026, 8, 30, 13, 31, tzinfo=UTC),
        recv_ts=datetime(2026, 8, 30, 13, 31, 1, tzinfo=UTC),
    )
    assert event.stream == "gap"
    assert event.payload["seq_from"] == 6
    assert event.payload["seq_to"] == 7


def test_contiguous_seq_is_not_a_gap() -> None:
    assert GapDetector().on_seq(5, 6) is None


def test_first_seq_is_not_a_gap() -> None:
    assert GapDetector().on_seq(None, 1) is None

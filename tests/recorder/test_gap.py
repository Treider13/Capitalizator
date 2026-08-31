"""0.1.6: seq 5 → 8 is exactly one gap covering 6–7."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from capitalizator.recorder.gap import GapDetector, SeqFault
from capitalizator.recorder.sink_parquet import ParquetSink


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


def test_duplicate_seq_is_not_swallowed() -> None:
    with pytest.raises(SeqFault, match="not monotonic"):
        GapDetector().on_seq(5, 5)


def test_gap_event_writes_parquet_partition(tmp_path: Path) -> None:
    detector = GapDetector()
    gap = detector.on_seq(5, 8)
    assert gap is not None
    event = detector.event(
        gap,
        symbol="BTCUSDT",
        stream="book_diff",
        exchange="bybit",
        exchange_ts=datetime(2026, 8, 30, 13, 31, tzinfo=UTC),
        recv_ts=datetime(2026, 8, 30, 13, 31, 1, tzinfo=UTC),
    )
    path = ParquetSink(tmp_path).write(event)
    assert path == tmp_path / "bybit" / "BTCUSDT" / "gap" / "date=2026-08-30" / "hour=13.parquet"
    assert pq.ParquetFile(path).read().num_rows == 1


def test_rewind_seq_is_not_swallowed() -> None:
    with pytest.raises(SeqFault, match="not monotonic"):
        GapDetector().on_seq(8, 5)

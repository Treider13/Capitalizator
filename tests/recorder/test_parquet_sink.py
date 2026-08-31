"""0.1.5: parquet rows == accepted_count, path is hourly partition."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pyarrow.parquet as pq

from capitalizator.recorder.sink_parquet import ParquetSink, partition_path
from capitalizator.types import MarketEvent


def _event(seq: int) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=datetime(2026, 8, 30, 13, 30, seq, tzinfo=UTC),
        recv_ts=datetime(2026, 8, 30, 13, 30, seq, 1, tzinfo=UTC),
        seq=seq,
        payload={"px": "65000", "qty": "0.001", "side": "buy"},
    )


def test_row_count_matches_accepted(tmp_path: Path) -> None:
    sink = ParquetSink(tmp_path)
    path = None
    for seq in range(1, 6):
        path = sink.write(_event(seq))
    assert path is not None
    assert sink.accepted_count == 5
    assert pq.ParquetFile(path).read().num_rows == 5
    expected = (
        tmp_path / "bybit" / "BTCUSDT" / "trades" / "date=2026-08-30" / "hour=13.parquet"
    )
    assert path == expected
    assert partition_path(tmp_path, _event(1)) == expected


def test_snapshot_and_book_diff_and_resync_partitions(tmp_path: Path) -> None:
    sink = ParquetSink(tmp_path)
    ts = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    for stream in ("snapshot", "book_diff", "bbo", "resync"):
        path = sink.write(
            MarketEvent(
                stream=stream,
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                seq=1,
                payload={"kind": stream},
            )
        )
        assert path == tmp_path / "bybit" / "BTCUSDT" / stream / "date=2026-08-30" / "hour=13.parquet"
        assert pq.ParquetFile(path).read().num_rows == 1


def test_failed_write_leaves_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sink = ParquetSink(tmp_path)
    path = sink.write(_event(1))
    old = path.read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(pq, "write_table", boom)
    with pytest.raises(OSError, match="disk"):
        sink.write(_event(2))
    assert path.read_bytes() == old
    assert list(path.parent.glob("*.tmp")) == []


def test_write_does_not_follow_predictable_tmp_symlink(tmp_path: Path) -> None:
    import os

    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    path = partition_path(tmp_path, _event(1))
    path.parent.mkdir(parents=True, exist_ok=True)
    planted = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    planted.symlink_to(secret)
    ParquetSink(tmp_path).write(_event(1))
    assert secret.read_bytes() == b"KEYMATERIAL"
    assert path.is_file() and not path.is_symlink()
    assert pq.ParquetFile(path).read().num_rows == 1


def test_write_refuses_lock_symlink(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    path = partition_path(tmp_path, _event(1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_name(f"{path.name}.lock").symlink_to(secret)
    with pytest.raises(OSError):
        ParquetSink(tmp_path).write(_event(1))
    assert secret.read_bytes() == b"KEYMATERIAL"


def test_concurrent_writers_keep_all_rows(tmp_path: Path) -> None:
    errors: list[BaseException] = []

    def go(seq: int) -> None:
        try:
            ParquetSink(tmp_path).write(_event(seq))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(seq,)) for seq in range(1, 6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    path = partition_path(tmp_path, _event(1))
    assert pq.ParquetFile(path).read().num_rows == 5


def test_new_sink_reloads_existing_file(tmp_path: Path) -> None:
    first = ParquetSink(tmp_path)
    path = first.write(_event(1))
    first.write(_event(2))
    second = ParquetSink(tmp_path)
    second.write(_event(3))
    assert pq.ParquetFile(path).read().num_rows == 3
    assert second.accepted_count == 1

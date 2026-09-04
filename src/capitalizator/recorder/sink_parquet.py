"""Append MarketEvents to hourly Parquet partitions. Count is exact.

Write goes to a mkstemp inode, then replace only if that name still is our file.
A live pack never copies a half-written parquet. Two writers take flock and reread.
"""

from __future__ import annotations

import fcntl
import io
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from capitalizator.ops.vault import (
    VaultError,
    assert_no_symlink_components,
    ensure_real_parent,
    mkdir_real_parents,
    mkstemp_at,
    open_real_dir_fd,
    replace_at,
    write_all,
)
from capitalizator.types import MarketEvent

SCHEMA = pa.schema(
    [
        ("stream", pa.string()),
        ("exchange", pa.string()),
        ("symbol", pa.string()),
        ("exchange_ts", pa.timestamp("us", tz="UTC")),
        ("recv_ts", pa.timestamp("us", tz="UTC")),
        ("seq", pa.int64()),
        ("payload_json", pa.string()),
    ]
)


def partition_path(data_root: Path, event: MarketEvent) -> Path:
    day = event.exchange_ts.strftime("%Y-%m-%d")
    hour = event.exchange_ts.strftime("%H")
    return (
        data_root
        / event.exchange
        / event.symbol
        / event.stream
        / f"date={day}"
        / f"hour={hour}.parquet"
    )


def _row(event: MarketEvent) -> dict:
    return {
        "stream": event.stream,
        "exchange": event.exchange,
        "symbol": event.symbol,
        "exchange_ts": event.exchange_ts,
        "recv_ts": event.recv_ts,
        "seq": event.seq,
        "payload_json": json.dumps(event.payload, separators=(",", ":")),
    }


def live_row(row: dict) -> dict:
    """The parquet row with timestamps as ISO strings — one JSON line of the live feed."""
    return {
        **row,
        "exchange_ts": row["exchange_ts"].isoformat(),
        "recv_ts": row["recv_ts"].isoformat(),
    }


class ParquetSink:
    def __init__(
        self, data_root: Path, *, on_write: Callable[[], None] | None = None
    ) -> None:
        self.data_root = data_root
        self.accepted_count = 0
        self._rows: dict[Path, list[dict]] = {}
        self._on_write = on_write

    def _notify(self) -> None:
        if self._on_write is not None:
            self._on_write()

    def write(self, event: MarketEvent) -> Path:
        path = partition_path(self.data_root, event)
        try:
            ensure_real_parent(self.data_root)
        except VaultError as exc:
            raise ValueError(str(exc)) from exc
        if self.data_root.is_symlink() or not self.data_root.is_dir():
            raise ValueError(f"symlink: {self.data_root}")
        mkdir_real_parents(self.data_root, path.parent)
        assert_no_symlink_components(self.data_root, path)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ValueError("O_NOFOLLOW required")
        dir_fd = open_real_dir_fd(path.parent)
        lock_fd = -1
        fd = -1
        tmp_name: str | None = None
        try:
            lock_fd = os.open(
                f"{path.name}.lock",
                os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | nofollow,
                0o644,
                dir_fd=dir_fd,
            )
            lock_st = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_st.st_mode):
                raise ValueError(f"not a regular file: {path.name}.lock")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            rows: list[dict] = []
            try:
                exist_fd = os.open(path.name, os.O_RDONLY | nofollow, dir_fd=dir_fd)
            except FileNotFoundError:
                exist_fd = -1
            except OSError as exc:
                raise ValueError(f"symlink: {path}") from exc
            if exist_fd >= 0:
                with os.fdopen(exist_fd, "rb") as fh:
                    rows.extend(pq.ParquetFile(fh).read().to_pylist())
            rows.append(_row(event))
            table = pa.Table.from_pylist(rows, schema=SCHEMA)
            buf = io.BytesIO()
            pq.write_table(table, buf)
            fd, tmp_name = mkstemp_at(dir_fd, prefix=f"{path.name}.", suffix=".tmp")
            created = os.fstat(fd)
            write_all(fd, buf.getvalue())
            os.fsync(fd)
            os.close(fd)
            fd = -1
            replace_at(dir_fd, tmp_name, path.name, created)
            tmp_name = None
            self._rows[path] = rows
            self.accepted_count += 1
            self._notify()
            return path
        except VaultError as exc:
            if fd >= 0:
                os.close(fd)
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name, dir_fd=dir_fd)
                except OSError:
                    pass
            raise ValueError(str(exc)) from exc
        except Exception:
            if fd >= 0:
                os.close(fd)
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name, dir_fd=dir_fd)
                except OSError:
                    pass
            raise
        finally:
            if lock_fd >= 0:
                os.close(lock_fd)
            os.close(dir_fd)


class BufferedParquetSink:
    """Live sink: buffer events, flush one immutable part file per partition.

    `ParquetSink.write` re-reads and rewrites the whole hourly file for every
    event (O(rows) per print — impossible at a live rate). This sink appends
    `hour=HH.<seq>.parquet` parts; readers glob `*.parquet` so parts and the
    single-file layout coexist. Part files are never rewritten.
    """

    def __init__(
        self,
        data_root: Path,
        *,
        flush_every_s: float = 1.0,
        max_rows: int = 5000,
        live_jsonl: bool = False,
        on_write: Callable[[], None] | None = None,
    ):
        if flush_every_s <= 0 or max_rows <= 0:
            raise ValueError("flush_every_s and max_rows must be > 0")
        self.data_root = data_root
        self.flush_every_s = flush_every_s
        self.max_rows = max_rows
        self._on_write = on_write
        # Live feed: every event is also appended, at once, to `hour=HH.jsonl` next to
        # the parquet parts. The desk tails it by byte offset (O(1) per tick) while the
        # parquet archive can flush rarely and compact — 24 symbols × 4 streams × 1 s
        # flushes produced ~5 800 part files a minute on the VPS (2026-09-03).
        self.live_jsonl = live_jsonl
        self.accepted_count = 0
        self.flushed_count = 0
        self.parts_written = 0
        self._buf: dict[Path, list[dict]] = {}
        self._seq: dict[Path, int] = {}
        self._last_flush: float | None = None
        self._live: dict[Path, Any] = {}

    def write(self, event: MarketEvent, *, now_monotonic: float | None = None) -> None:
        path = partition_path(self.data_root, event)
        row = _row(event)
        self._buf.setdefault(path, []).append(row)
        self.accepted_count += 1
        if self.live_jsonl:
            self._append_live(path, row)
            self._notify()
        if sum(len(rows) for rows in self._buf.values()) >= self.max_rows:
            self.flush()
        elif now_monotonic is not None:
            self.maybe_flush(now_monotonic)

    def _notify(self) -> None:
        if self._on_write is not None:
            self._on_write()

    # --- live jsonl ------------------------------------------------------------------
    def _append_live(self, hour_path: Path, row: dict) -> None:
        live_path = hour_path.with_suffix(".jsonl")
        fh = self._live.get(live_path)
        if fh is None:
            mkdir_real_parents(self.data_root, live_path.parent)
            assert_no_symlink_components(self.data_root, live_path)
            # one open handle per partition (symbol × stream); close only the handles of
            # OTHER hours of the same partition (audit B12: everything else was closed
            # and reopened on every event of another symbol)
            same_partition = live_path.parent.parent  # …/<stream>/
            for other, old in list(self._live.items()):
                if other.parent.parent != same_partition or other == live_path:
                    continue  # another symbol/stream keeps its handle
                try:
                    old.close()  # an older hour (or day) of this partition
                finally:
                    del self._live[other]
            fh = open(live_path, "a", encoding="utf-8", buffering=1)  # line-buffered
            self._live[live_path] = fh
        fh.write(json.dumps(live_row(row), separators=(",", ":")) + "\n")

    def close(self) -> None:
        for fh in self._live.values():
            try:
                fh.close()
            except OSError:
                pass
        self._live.clear()

    def maybe_flush(self, now_monotonic: float) -> int:
        if self._last_flush is None:
            self._last_flush = now_monotonic
            return 0
        if now_monotonic - self._last_flush >= self.flush_every_s:
            n = self.flush()
            self._last_flush = now_monotonic
            return n
        return 0

    def pending(self) -> int:
        return sum(len(rows) for rows in self._buf.values())

    def flush(self) -> int:
        """Write every buffered partition as a new part. Returns rows written."""
        written = 0
        for hour_path, rows in list(self._buf.items()):
            if not rows:
                continue
            self._write_part(hour_path, rows)
            written += len(rows)
            del self._buf[hour_path]
        self.flushed_count += written
        if written and not self.live_jsonl:
            self._notify()
        return written

    def _write_part(self, hour_path: Path, rows: list[dict]) -> Path:
        try:
            ensure_real_parent(self.data_root)
        except VaultError as exc:
            raise ValueError(str(exc)) from exc
        if self.data_root.is_symlink() or not self.data_root.is_dir():
            raise ValueError(f"symlink: {self.data_root}")
        mkdir_real_parents(self.data_root, hour_path.parent)
        assert_no_symlink_components(self.data_root, hour_path)
        seq = self._seq.get(hour_path, 0)
        # Pick a name that does not exist yet (another writer may share the dir).
        while True:
            part = hour_path.with_name(f"{hour_path.stem}.{seq:06d}.parquet")
            if not part.exists():
                break
            seq += 1
        self._seq[hour_path] = seq + 1
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        buf = io.BytesIO()
        # zstd: ~2–3× smaller than snappy on JSON payload columns; the archive is
        # what fills the disk (4 MB / 90 s for BTC+ETH L2 on the VPS).
        pq.write_table(table, buf, compression="zstd")
        dir_fd = open_real_dir_fd(hour_path.parent)
        fd = -1
        tmp_name: str | None = None
        try:
            fd, tmp_name = mkstemp_at(dir_fd, prefix=f"{part.name}.", suffix=".tmp")
            created = os.fstat(fd)
            write_all(fd, buf.getvalue())
            os.fsync(fd)
            os.close(fd)
            fd = -1
            replace_at(dir_fd, tmp_name, part.name, created)
            tmp_name = None
            self.parts_written += 1
            return part
        except VaultError as exc:
            raise ValueError(str(exc)) from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name, dir_fd=dir_fd)
                except OSError:
                    pass
            os.close(dir_fd)

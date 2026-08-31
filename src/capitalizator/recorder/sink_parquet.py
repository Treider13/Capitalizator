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
from pathlib import Path

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


class ParquetSink:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.accepted_count = 0
        self._rows: dict[Path, list[dict]] = {}

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
            os.write(fd, buf.getvalue())
            os.fsync(fd)
            os.close(fd)
            fd = -1
            replace_at(dir_fd, tmp_name, path.name, created)
            tmp_name = None
            self._rows[path] = rows
            self.accepted_count += 1
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

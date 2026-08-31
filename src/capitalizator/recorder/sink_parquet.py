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
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from capitalizator.ops.vault import (
    VaultError,
    assert_no_symlink_components,
    ensure_real_parent,
    mkdir_real_parents,
    open_regular,
    replace_if_same,
    same_inode,
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


def _read_existing(path: Path) -> pa.Table:
    fd = open_regular(path)
    with os.fdopen(fd, "rb") as fh:
        return pq.ParquetFile(fh).read()


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
        if path.is_symlink():
            raise ValueError(f"symlink: {path}")
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ValueError("O_NOFOLLOW required")
        lock_path = path.with_name(f"{path.name}.lock")
        lock_fd = os.open(
            lock_path, os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | nofollow, 0o644
        )
        tmp: Path | None = None
        created = None
        fd = -1
        try:
            lock_st = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_st.st_mode):
                raise ValueError(f"not a regular file: {lock_path}")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            rows: list[dict] = []
            if path.is_symlink():
                raise ValueError(f"symlink: {path}")
            if path.exists():
                rows.extend(_read_existing(path).to_pylist())
            rows.append(_row(event))
            table = pa.Table.from_pylist(rows, schema=SCHEMA)
            buf = io.BytesIO()
            pq.write_table(table, buf)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
            )
            tmp = Path(tmp_name)
            created = os.fstat(fd)
            os.write(fd, buf.getvalue())
            os.fsync(fd)
            os.close(fd)
            fd = -1
            replace_if_same(tmp, path, created)
            self._rows[path] = rows
            self.accepted_count += 1
            return path
        except Exception:
            if fd >= 0:
                os.close(fd)
            if tmp is not None and created is not None and same_inode(tmp, created):
                tmp.unlink()
            raise
        finally:
            os.close(lock_fd)

"""Append MarketEvents to hourly Parquet partitions. Count is exact.

Write goes to a sibling tmp file, then replace(). A live pack never copies a
half-written parquet (the old complete file stays until the rename).
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

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
    # ParquetFile avoids hive-partition columns inferred from date= dirs.
    return pq.ParquetFile(path).read()


class ParquetSink:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.accepted_count = 0
        self._rows: dict[Path, list[dict]] = {}

    def write(self, event: MarketEvent) -> Path:
        path = partition_path(self.data_root, event)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError(f"symlink: {path}")
        lock_path = path.with_name(f"{path.name}.lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            rows: list[dict] = []
            if path.exists():
                if path.is_symlink():
                    raise ValueError(f"symlink: {path}")
                rows.extend(_read_existing(path).to_pylist())
            rows.append(_row(event))
            table = pa.Table.from_pylist(rows, schema=SCHEMA)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            try:
                pq.write_table(table, tmp)
                tmp.replace(path)
            except Exception:
                if tmp.exists() and not tmp.is_symlink():
                    tmp.unlink()
                raise
            self._rows[path] = rows
            self.accepted_count += 1
            return path
        finally:
            os.close(lock_fd)

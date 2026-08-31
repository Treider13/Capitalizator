"""Append MarketEvents to hourly Parquet partitions. Count is exact."""

from __future__ import annotations

import json
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
        if path not in self._rows:
            self._rows[path] = []
            if path.exists():
                loaded = _read_existing(path)
                self._rows[path].extend(loaded.to_pylist())
        self._rows[path].append(_row(event))
        table = pa.Table.from_pylist(self._rows[path], schema=SCHEMA)
        pq.write_table(table, path)
        self.accepted_count += 1
        return path

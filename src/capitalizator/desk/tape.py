"""Read recorded parquet into desk. Regular files only. No invented rows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.vault import VaultError, iter_regular_files
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

Seen = set[tuple[str, str, str, int | None]]


def _parse(row: dict) -> MarketEvent | None:
    try:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            return None
        ts = row["exchange_ts"]
        recv = row["recv_ts"]
        if not isinstance(ts, datetime) or not isinstance(recv, datetime):
            return None
        return MarketEvent(
            stream=row["stream"],
            exchange=row["exchange"],
            symbol=row["symbol"],
            exchange_ts=ts,
            recv_ts=recv,
            seq=row.get("seq"),
            payload=payload,
        )
    except (TypeError, ValueError, json.JSONDecodeError, KeyError):
        return None


def load_tape(tape: Path) -> list[MarketEvent]:
    if tape.is_symlink() or not tape.is_dir():
        return []
    events: list[MarketEvent] = []
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return []
    for path in paths:
        if path.suffix != ".parquet":
            continue
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, ValueError):
            continue
        for row in table.to_pylist():
            event = _parse(row)
            if event is not None:
                events.append(event)
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


def consume_tape(
    desk: DeskLoop,
    tape: Path,
    *,
    seen: Seen,
    extra_zones: tuple[Zone, ...] = (),
) -> int:
    """Feed unseen parquet events into the loop. Second pass does not replay."""
    n = 0
    zones = list(extra_zones)
    for event in load_tape(tape):
        key = (event.stream, event.symbol, event.exchange_ts.isoformat(), event.seq)
        if key in seen:
            continue
        seen.add(key)
        desk.on_event(event, zones if event.stream == "trades" else None)
        n += 1
    return n

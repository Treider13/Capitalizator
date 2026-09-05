"""One calendar day of recorded parquet. Skips other days so a month of tape
does not load into RAM (live desk OOM 2026-09-03). No invented rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pyarrow.parquet as pq

from capitalizator.desk.tape import _parse
from capitalizator.ops.vault import VaultError, iter_regular_files
from capitalizator.recorder.rows import rows_fast
from capitalizator.types import MarketEvent

TRADE_STREAM = "trades"


def _day_part(day: str) -> str:
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise ValueError("day must be YYYY-MM-DD")
    return f"date={day}"


def load_day_events(
    tape: Path,
    day: str,
    *,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> list[MarketEvent]:
    """Parquet partitions for `date=YYYY-MM-DD` only. Empty tape → []."""
    if tape.is_symlink() or not tape.is_dir():
        return []
    wanted_day = _day_part(day)
    wanted_streams = set(streams) if streams is not None else None
    events: list[MarketEvent] = []
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return []
    for path in paths:
        if path.suffix != ".parquet":
            continue
        if wanted_day not in path.parts:
            continue
        if wanted_streams is not None and not wanted_streams.intersection(path.parts):
            continue
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, ValueError):
            continue
        for row in rows_fast(table):
            event = _parse(row)
            if event is None:
                continue
            if symbols is not None and event.symbol not in symbols:
                continue
            if wanted_streams is not None and event.stream not in wanted_streams:
                continue
            events.append(event)
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


def load_trade_events(tape: Path, *, symbols: set[str]) -> list[MarketEvent]:
    """Trade prints only — backfill does not need the book. All dates for those symbols."""
    if tape.is_symlink() or not tape.is_dir() or not symbols:
        return []
    events: list[MarketEvent] = []
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return []
    for path in paths:
        if path.suffix != ".parquet":
            continue
        if TRADE_STREAM not in path.parts:
            continue
        if symbols.isdisjoint(path.parts):
            continue
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, ValueError):
            continue
        for row in rows_fast(table):
            event = _parse(row)
            if event is None or event.stream != TRADE_STREAM:
                continue
            if event.symbol not in symbols:
                continue
            events.append(event)
    events.sort(key=lambda e: (e.exchange_ts, e.symbol))
    return events

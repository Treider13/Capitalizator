"""One calendar day of recorded tape. Skips other days so a month of tape
does not load into RAM (live desk OOM 2026-09-03). No invented rows.

Reads the live `hour=HH.jsonl` feed and the parquet archive. When both exist
for the same hour the jsonl wins (same law as TapeCursor).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pyarrow.parquet as pq

from capitalizator.desk.tape import _parse, event_from_jsonl_line
from capitalizator.ops.vault import VaultError, iter_regular_files
from capitalizator.recorder.rows import rows_fast
from capitalizator.types import MarketEvent

TRADE_STREAM = "trades"


def _day_part(day: str) -> str:
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise ValueError("day must be YYYY-MM-DD")
    return f"date={day}"


def _hour_key(path: Path) -> Path:
    return path.parent / path.name.split(".")[0]


def _wanted_stream(path: Path, streams: set[str] | None) -> bool:
    if streams is None:
        return True
    return bool(streams.intersection(path.parts))


def _read_jsonl(
    path: Path,
    *,
    symbols: set[str] | None,
    streams: set[str] | None,
) -> list[MarketEvent]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[MarketEvent] = []
    for line in text.splitlines():
        event = event_from_jsonl_line(line)
        if event is None:
            continue
        if symbols is not None and event.symbol not in symbols:
            continue
        if streams is not None and event.stream not in streams:
            continue
        out.append(event)
    return out


def _read_parquet(
    path: Path,
    *,
    symbols: set[str] | None,
    streams: set[str] | None,
) -> list[MarketEvent]:
    try:
        table = pq.ParquetFile(path).read()
    except (OSError, ValueError):
        return []
    out: list[MarketEvent] = []
    for row in rows_fast(table):
        event = _parse(row)
        if event is None:
            continue
        if symbols is not None and event.symbol not in symbols:
            continue
        if streams is not None and event.stream not in streams:
            continue
        out.append(event)
    return out


def _load(
    tape: Path,
    *,
    day: str | None = None,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> list[MarketEvent]:
    if tape.is_symlink() or not tape.is_dir():
        return []
    wanted_day = _day_part(day) if day is not None else None
    wanted_streams = set(streams) if streams is not None else None
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return []
    jsonl: list[Path] = []
    parquet: list[Path] = []
    for path in paths:
        if wanted_day is not None and wanted_day not in path.parts:
            continue
        if not _wanted_stream(path, wanted_streams):
            continue
        if symbols is not None and symbols.isdisjoint(path.parts):
            continue
        if path.suffix == ".jsonl":
            jsonl.append(path)
        elif path.suffix == ".parquet":
            parquet.append(path)
    live = {_hour_key(path) for path in jsonl}
    events: list[MarketEvent] = []
    for path in jsonl:
        events.extend(_read_jsonl(path, symbols=symbols, streams=wanted_streams))
    for path in parquet:
        if _hour_key(path) in live:
            continue
        events.extend(_read_parquet(path, symbols=symbols, streams=wanted_streams))
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


def load_day_events(
    tape: Path,
    day: str,
    *,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> list[MarketEvent]:
    """`date=YYYY-MM-DD` only: jsonl live feed, then parquet for hours without it."""
    return _load(tape, day=day, streams=streams, symbols=symbols)


def load_trade_events(tape: Path, *, symbols: set[str]) -> list[MarketEvent]:
    """Trade prints only — backfill does not need the book. All dates for those symbols."""
    if not symbols:
        return []
    return _load(tape, streams=(TRADE_STREAM,), symbols=symbols)

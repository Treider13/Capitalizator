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


def _hour_part(path: Path) -> str:
    for part in path.parts:
        if part.startswith("hour="):
            return part[:7]
    return ""


def _collect_paths(
    tape: Path,
    *,
    day: str | None = None,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> tuple[list[Path], list[Path]]:
    if tape.is_symlink() or not tape.is_dir():
        return [], []
    wanted_day = _day_part(day) if day is not None else None
    wanted_streams = set(streams) if streams is not None else None
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return [], []
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
    return jsonl, parquet


def _events_for_hour(
    jsonl: list[Path],
    parquet: list[Path],
    *,
    symbols: set[str] | None,
    streams: set[str] | None,
) -> list[MarketEvent]:
    live = {_hour_key(path) for path in jsonl}
    events: list[MarketEvent] = []
    for path in jsonl:
        events.extend(_read_jsonl(path, symbols=symbols, streams=streams))
    for path in parquet:
        if _hour_key(path) in live:
            continue
        events.extend(_read_parquet(path, symbols=symbols, streams=streams))
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


def iter_day_hours(
    tape: Path,
    day: str,
    *,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> list[list[MarketEvent]]:
    """One list per hour of that day. Peak RAM is one hour, not the whole book day.

    Two days of BTC+ETH jsonl were 3 GB and OOM'd the live loop (2026-09-03).
    Replay still sees every stream of the hour — it does not drop the book.
    """
    jsonl, parquet = _collect_paths(tape, day=day, streams=streams, symbols=symbols)
    wanted_streams = set(streams) if streams is not None else None
    by_hour: dict[str, tuple[list[Path], list[Path]]] = {}
    for path in jsonl:
        hour = _hour_part(path)
        pair = by_hour.setdefault(hour, ([], []))
        pair[0].append(path)
    for path in parquet:
        hour = _hour_part(path)
        pair = by_hour.setdefault(hour, ([], []))
        pair[1].append(path)
    out: list[list[MarketEvent]] = []
    for hour in sorted(by_hour):
        hour_jsonl, hour_pq = by_hour[hour]
        events = _events_for_hour(
            hour_jsonl, hour_pq, symbols=symbols, streams=wanted_streams
        )
        if events:
            out.append(events)
    return out


def _load(
    tape: Path,
    *,
    day: str | None = None,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> list[MarketEvent]:
    if day is not None:
        events: list[MarketEvent] = []
        for hour in iter_day_hours(tape, day, streams=streams, symbols=symbols):
            events.extend(hour)
        return events
    jsonl, parquet = _collect_paths(tape, streams=streams, symbols=symbols)
    wanted_streams = set(streams) if streams is not None else None
    return _events_for_hour(jsonl, parquet, symbols=symbols, streams=wanted_streams)


def load_day_events(
    tape: Path,
    day: str,
    *,
    streams: Sequence[str] | None = None,
    symbols: set[str] | None = None,
) -> list[MarketEvent]:
    """`date=YYYY-MM-DD` only: jsonl live feed, then parquet for hours without it."""
    events: list[MarketEvent] = []
    for hour in iter_day_hours(tape, day, streams=streams, symbols=symbols):
        events.extend(hour)
    return events


def load_trade_events(tape: Path, *, symbols: set[str]) -> list[MarketEvent]:
    """Trade prints only — backfill does not need the book. All dates for those symbols."""
    if not symbols:
        return []
    return _load(tape, streams=(TRADE_STREAM,), symbols=symbols)

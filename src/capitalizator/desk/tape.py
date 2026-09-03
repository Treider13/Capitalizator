"""Read recorded parquet into desk. Regular files only. No invented rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from capitalizator.card.live import CardLive
from capitalizator.desk.bars import closed_bars_from_trades
from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.vault import VaultError, iter_regular_files
from capitalizator.recorder.rows import rows_fast
from capitalizator.types import MarketEvent
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Zone

Seen = set[tuple[str, str, str, int | None]]
_MSK = ZoneInfo("Europe/Moscow")


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
        for row in rows_fast(table):
            event = _parse(row)
            if event is not None:
                events.append(event)
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


class TapeCursor:
    """Per-file read position so a 1s serve loop does not re-parse the whole tape.

    Two layers, same rows:
      * `hour=HH.jsonl` — the recorder's live feed, appended per event. Tailed by byte
        offset: O(new bytes) per tick, no re-parse, no per-second part files.
      * `hour=HH*.parquet` — the archive (parts, later compacted). Read once each; used
        for hours that have no live feed (backfill, old recordings, fixtures).
    The first pass reads the whole tape (backfill after a restart, fixtures); every
    later pass scans only partitions of the last `RECENT_DAYS`: a month of tape is
    hundreds of thousands of files and `os.walk` over all of them every second was
    the desk's own latency (2026-09-03). `seen` dedup guards a rewritten file.
    """

    RECENT_DAYS = 2

    def __init__(self, *, recent_days: int | None = None) -> None:
        self._pos: dict[Path, tuple[int, int, int]] = {}
        self._tail: dict[Path, int] = {}  # jsonl → bytes consumed
        self._partial: dict[Path, str] = {}  # jsonl → unfinished last line
        self.files_scanned = 0
        self.files_read = 0
        self.recent_days = self.RECENT_DAYS if recent_days is None else recent_days
        self._first_pass_done = False

    def _recent(self, path: Path, now: datetime | None) -> bool:
        if not self._first_pass_done or now is None or self.recent_days <= 0:
            return True
        for part in path.parts:
            if part.startswith("date="):
                try:
                    day = datetime.strptime(part[5:], "%Y-%m-%d").date()
                except ValueError:
                    return True
                return (now.date() - day).days <= self.recent_days
        return True

    def fresh_rows(self, tape: Path, *, now: datetime | None = None) -> list[MarketEvent]:
        if tape.is_symlink() or not tape.is_dir():
            return []
        try:
            paths = [p for p in iter_regular_files(tape) if self._recent(p, now)]
        except VaultError:
            return []
        self._first_pass_done = True
        events: list[MarketEvent] = []
        live_dirs: set[Path] = set()
        for path in paths:
            if path.suffix == ".jsonl":
                live_dirs.add(path.parent / path.stem)  # hour=HH key
                events.extend(self._tail_jsonl(path))
        for path in paths:
            if path.suffix != ".parquet":
                continue
            # `hour=HH.000123.parquet` → stem `hour=HH.000123`; live key is `hour=HH`
            hour_key = path.parent / path.name.split(".")[0]
            if hour_key in live_dirs:
                continue  # the live feed already delivered these rows
            self.files_scanned += 1
            try:
                st = path.stat()
            except OSError:
                continue
            size, mtime = st.st_size, st.st_mtime_ns
            prev = self._pos.get(path)
            if prev is not None and prev[0] == size and prev[1] == mtime:
                continue
            offset = prev[2] if prev is not None else 0
            try:
                table = pq.ParquetFile(path).read()
            except (OSError, ValueError):
                continue
            self.files_read += 1
            rows = rows_fast(table)
            for row in rows[offset:]:
                event = _parse(row)
                if event is not None:
                    events.append(event)
            self._pos[path] = (size, mtime, len(rows))
        events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
        return events

    def _tail_jsonl(self, path: Path) -> list[MarketEvent]:
        self.files_scanned += 1
        try:
            size = path.stat().st_size
        except OSError:
            return []
        start = self._tail.get(path, 0)
        if size < start:  # truncated/rotated: start over
            start = 0
            self._partial.pop(path, None)
        if size == start:
            return []
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                chunk = fh.read(size - start)
        except OSError:
            return []
        self.files_read += 1
        self._tail[path] = size
        text = self._partial.pop(path, "") + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        if not text.endswith("\n"):
            self._partial[path] = lines.pop()  # incomplete line: wait for the rest
        else:
            lines.pop()  # trailing empty
        out: list[MarketEvent] = []
        for line in lines:
            if not line:
                continue
            try:
                row = json.loads(line)
                row["exchange_ts"] = datetime.fromisoformat(row["exchange_ts"])
                row["recv_ts"] = datetime.fromisoformat(row["recv_ts"])
            except (ValueError, KeyError, TypeError):
                continue
            event = _parse(row)
            if event is not None:
                out.append(event)
        return out


def consume_tape(
    desk: DeskLoop,
    tape: Path,
    *,
    seen: Seen,
    extra_zones: tuple[Zone, ...] = (),
    now: datetime | None = None,
    cursor: TapeCursor | None = None,
) -> int:
    """Feed unseen parquet events into the loop. Second pass does not replay.

    With a `cursor` only changed files are parsed; without it (one-shot `--once`,
    old tests) the whole tape is loaded as before.
    """
    fresh: list[MarketEvent] = []
    source = cursor.fresh_rows(tape, now=now) if cursor is not None else load_tape(tape)
    for event in source:
        key = (event.stream, event.symbol, event.exchange_ts.isoformat(), event.seq)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(event)
    desk.play(fresh, extra_zones=extra_zones, now=now)
    return len(fresh)


def zones_for_trade(
    desk: DeskLoop,
    event: MarketEvent,
    extra_zones: Sequence[Zone] = (),
    card: CardLive | None = None,
) -> list[Zone]:
    """Prior-day / swing zones. POC comes from the live B card, not a VWAP stand-in.

    The map only changes when a working bar closes, the POC moves, the UTC date
    flips or the Moscow session boundary passes — so it is cached on that key
    instead of being rebuilt on every print.
    """
    tf = desk.config.working_tf
    st = desk.state_for(event.symbol)
    work = [b for b in st.bars if b.tf == tf]
    live = card if card is not None else desk._card_for(event.symbol, event.exchange_ts)
    poc = _poc_from_card(live)
    when = event.exchange_ts
    local = when.astimezone(_MSK)
    key = (
        len(work),
        work[-1].close_ts if work else None,
        poc,
        when.date(),
        local.hour * 60 + local.minute >= 16 * 60 + 30,
        len(st.bars),
    )
    cached = desk.zone_cache.get(event.symbol)
    if cached is not None and cached[0] == key:
        return list(extra_zones) + list(cached[1])
    engine = ZoneEngine(tick_size=desk.tick_for(event.symbol), config=desk.config)
    built = engine.build(event.symbol, when, work, poc=poc)
    desk.zone_cache[event.symbol] = (key, tuple(built))
    return list(extra_zones) + built


def _poc_from_card(card: object) -> Decimal | None:
    volume = getattr(card, "volume", None)
    raw = getattr(volume, "poc", None) if volume is not None else None
    if not raw:
        return None
    try:
        value = Decimal(str(raw))
    except Exception:
        return None
    return value if value > 0 else None


def close_due_bars(desk: DeskLoop, symbol: str, now: datetime) -> list[dict[str, Any]]:
    """Close working TF first, then H4 and D1. CAV is the 15m vote (§6.3/§6.5).

    Live path is the incremental BarBuilder (O(1) per print). The rescan over
    `st.trades` stays only for a state without a builder (old fixtures).
    """
    st = desk.state_for(symbol)
    out: list[dict[str, Any]] = []
    builder = st.bar_builder
    if builder is not None:
        if st.bars_seeded < len(st.bars):
            builder.seed_closed(st.bars[st.bars_seeded :])
            st.bars_seeded = len(st.bars)
        for bar in builder.close_due(now):
            out.extend(desk.on_bar_close(bar))
        st.bars_seeded = len(st.bars)
        return out
    tfs = (desk.config.working_tf, desk.config.htf, desk.config.htf_d1)
    for tf in tfs:
        already = {b.open_ts for b in st.bars if b.tf == tf}
        for bar in closed_bars_from_trades(
            st.trades, symbol=symbol, tf=tf, now=now, already=already
        ):
            out.extend(desk.on_bar_close(bar))
    return out


def _close_due_bars(desk: DeskLoop, symbol: str, now: datetime) -> None:
    close_due_bars(desk, symbol, now)

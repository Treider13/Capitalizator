"""Read recorded parquet into desk. Regular files only. No invented rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
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


def event_from_jsonl_line(line: str) -> MarketEvent | None:
    """One live-feed line (`hour=HH.jsonl`) → event, or None if the line is not a row."""
    if not line.strip():
        return None
    try:
        row = json.loads(line)
        row["exchange_ts"] = datetime.fromisoformat(str(row["exchange_ts"]))
        row["recv_ts"] = datetime.fromisoformat(str(row["recv_ts"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return _parse(row)


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

    Every pass is BOUNDED: at most `max_bytes` of jsonl and `max_rows` of parquet are
    turned into events, files are visited in (date, hour) order and a file that was not
    finished is resumed on the next pass. Two days of BTC+ETH tape are ~3 GB of JSON;
    read in one list they were 3.2 GB of RSS and the OOM killer restarted the desk
    every 30 s (VPS, 2026-09-03). Old `book_diff` rows are skipped on a production
    first pass (`book_hours`): a book is only valid from its next snapshot anyway.
    Official orderbook.200: snapshot, then delta. Origin jsonl is read first so a
    restart does not spend the byte budget on `book_diff` and never apply the
    snapshot (live SOLUSDT stayed empty). No time-seek stitch.
    """

    RECENT_DAYS = 2
    # sized so one pass stays well under the 30 s dead-man: a longer pass starves the
    # desk heartbeat and the signer blocks entries with reason `desk` while catching up
    MAX_BYTES = 8 * 1024 * 1024  # jsonl bytes per pass
    MAX_ROWS = 60_000  # parquet rows per pass
    BOOK_HOURS = 2  # production first pass: book deltas only this recent
    _BOOK_PARTS = frozenset({"book_diff", "snapshot", "bbo", "resync"})
    _BOOK_ORIGIN = frozenset({"snapshot", "resync"})
    _BOOK_DELTA = frozenset({"book_diff", "bbo"})

    def __init__(
        self,
        *,
        recent_days: int | None = None,
        replay_all_first: bool = True,
        max_bytes: int | None = None,
        max_rows: int | None = None,
        book_hours: int | None = None,
    ) -> None:
        self._pos: dict[Path, tuple[int, int, int]] = {}
        self._tail: dict[Path, int] = {}  # jsonl → bytes consumed
        self._partial: dict[Path, str] = {}  # jsonl → unfinished last line
        self.files_scanned = 0
        self.files_read = 0
        self.recent_days = self.RECENT_DAYS if recent_days is None else recent_days
        self.max_bytes = self.MAX_BYTES if max_bytes is None else max_bytes
        self.max_rows = self.MAX_ROWS if max_rows is None else max_rows
        # a 24/7 desk restarting on a month of tape must not replay the month:
        # `replay_all_first=False` makes even the first pass recent-only (audit A2/E)
        self._first_pass_done = not replay_all_first
        self._production = not replay_all_first
        self.book_hours = self.BOOK_HOURS if book_hours is None else book_hours
        self._skipped_book: set[Path] = set()
        self.backlog = False  # True while a pass hit its budget (replay still catching up)

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
            # prune old `date=` subtrees during the walk, not after it
            paths = [
                p
                for p in iter_regular_files(tape, keep_dir=lambda d: self._recent(d, now))
                if self._recent(p, now)
            ]
        except VaultError:
            return []
        self._first_pass_done = True
        paths.sort(key=_chrono_key)
        live_dirs: set[Path] = set()
        jsonl_paths: list[Path] = []
        parquet_paths: list[Path] = []
        for path in paths:
            if path.suffix == ".jsonl":
                jsonl_paths.append(path)
                live_dirs.add(path.parent / path.stem)  # hour=HH key
            elif path.suffix == ".parquet":
                parquet_paths.append(path)
        events: list[MarketEvent] = []
        budget_bytes = self.max_bytes
        budget_rows = self.max_rows
        self.backlog = False
        # Official: snapshot, then delta. Origin jsonl is small; it does not
        # share the delta/trade budget.
        # https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
        origin_jsonl = [p for p in jsonl_paths if _book_role(p) == "origin"]
        delta_jsonl = [p for p in jsonl_paths if _book_role(p) == "delta"]
        other_jsonl = [p for p in jsonl_paths if _book_role(p) is None]
        for path in origin_jsonl:
            if self._skip_old_book(path, now):
                continue
            got, used = self._tail_jsonl(path, max(self.max_bytes, 1 << 20))
            events.extend(got)
        for path in delta_jsonl:
            if self._skip_old_book(path, now):
                continue
            if budget_bytes <= 0:
                self.backlog = True
                break
            got, used = self._tail_jsonl(path, budget_bytes)
            events.extend(got)
            budget_bytes -= used
        for path in other_jsonl:
            if budget_bytes <= 0:
                self.backlog = True
                break
            got, used = self._tail_jsonl(path, budget_bytes)
            events.extend(got)
            budget_bytes -= used
        book_pq = [
            p
            for p in parquet_paths
            if _book_stream(p) is not None and not self._skip_old_book(p, now)
        ]
        origin_pq = [p for p in book_pq if _book_role(p) == "origin"]
        delta_pq = [p for p in book_pq if _book_role(p) != "origin"]
        other_pq = [p for p in parquet_paths if _book_stream(p) is None]
        book_pq = origin_pq + delta_pq
        for path in book_pq + other_pq:
            hour_key = path.parent / path.name.split(".")[0]
            if hour_key in live_dirs:
                continue  # the live feed already delivered these rows
            is_book = _book_stream(path) is not None
            if not is_book and budget_rows <= 0:
                self.backlog = True
                break
            row_cap = max(budget_rows, 50_000) if is_book else budget_rows
            got, used = self._read_parquet(path, row_cap)
            events.extend(got)
            if not is_book:
                budget_rows -= used
        events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
        return events

    def _skip_old_book(self, path: Path, now: datetime | None) -> bool:
        """Production: book rows older than `book_hours` are not replayed.

        Bybit: a book is snapshot then consecutive `u`; a hole is reset-local,
        not a stitch. Same law already in this module: a book is only valid
        from its next snapshot. Snapshot and diff share the window.
        """
        if not self._production or now is None or _book_stream(path) is None:
            return False
        if path in self._skipped_book:
            return True
        stamp = _partition_time(path)
        if stamp is None:
            return False
        if (now - stamp).total_seconds() > self.book_hours * 3600:
            self._skipped_book.add(path)
            return True
        return False

    def _read_parquet(self, path: Path, budget_rows: int) -> tuple[list[MarketEvent], int]:
        self.files_scanned += 1
        try:
            st = path.stat()
        except OSError:
            return [], 0
        size, mtime = st.st_size, st.st_mtime_ns
        prev = self._pos.get(path)
        if prev is not None and prev[0] == size and prev[1] == mtime and prev[2] < 0:
            return [], 0  # finished and unchanged
        offset = prev[2] if prev is not None and prev[2] >= 0 else 0
        if prev is not None and (prev[0] != size or prev[1] != mtime):
            offset = 0  # rewritten (compaction): start over; `seen` dedups the rest
        try:
            pf = pq.ParquetFile(path)
            total = pf.metadata.num_rows
        except (OSError, ValueError):
            return [], 0
        self.files_read += 1
        out: list[MarketEvent] = []
        seen_rows = 0
        wanted_end = min(total, offset + budget_rows)
        for batch in pf.iter_batches(batch_size=50_000):
            n = batch.num_rows
            if seen_rows + n <= offset:
                seen_rows += n
                continue
            rows = rows_fast(batch)
            lo = max(0, offset - seen_rows)
            hi = min(n, wanted_end - seen_rows)
            for row in rows[lo:hi]:
                event = _parse(row)
                if event is not None:
                    out.append(event)
            seen_rows += n
            if seen_rows >= wanted_end:
                break
        used = wanted_end - offset
        done = wanted_end >= total
        self._pos[path] = (size, mtime, -1 if done else wanted_end)
        if not done:
            self.backlog = True
        return out, used

    def _tail_jsonl(self, path: Path, budget: int) -> tuple[list[MarketEvent], int]:
        """Read at most `budget` new bytes from the live feed; returns (events, bytes)."""
        self.files_scanned += 1
        try:
            size = path.stat().st_size
        except OSError:
            return [], 0
        start = self._tail.get(path, 0)
        if size < start:  # truncated/rotated: start over
            start = 0
            self._partial.pop(path, None)
        if size == start:
            return [], 0
        want = min(size - start, budget)
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                chunk = fh.read(want)
        except OSError:
            return [], 0
        self.files_read += 1
        self._tail[path] = start + len(chunk)
        if start + len(chunk) < size:
            self.backlog = True
        # split on bytes, then decode: a read boundary inside a multibyte character
        # must not corrupt the tail (kept as the partial line)
        raw_lines = chunk.split(b"\n")
        partial = self._partial.pop(path, b"")
        if raw_lines:
            raw_lines[0] = partial + raw_lines[0]
        if not chunk.endswith(b"\n"):
            self._partial[path] = raw_lines.pop()  # incomplete line: wait for the rest
        else:
            raw_lines.pop()  # trailing empty
        out: list[MarketEvent] = []
        for raw in raw_lines:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace")
            event = event_from_jsonl_line(line)
            if event is not None:
                out.append(event)
        return out, len(chunk)


def _partition_time(path: Path) -> datetime | None:
    day = hour = None
    for part in path.parts:
        if part.startswith("date="):
            day = part[5:]
        elif part.startswith("hour="):
            hour = part[5:7]
    if day is None:
        return None
    try:
        stamp = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
        if hour is not None:
            stamp = stamp.replace(hour=int(hour))
        return stamp + timedelta(hours=1)  # the partition's last moment
    except ValueError:
        return None


def _book_stream(path: Path) -> str | None:
    for part in path.parts:
        if part in TapeCursor._BOOK_PARTS:
            return part
    return None


def _book_role(path: Path) -> str | None:
    stream = _book_stream(path)
    if stream in TapeCursor._BOOK_ORIGIN:
        return "origin"
    if stream in TapeCursor._BOOK_DELTA:
        return "delta"
    return None


def _chrono_key(path: Path) -> tuple[str, str, str]:
    day = hour = ""
    for part in path.parts:
        if part.startswith("date="):
            day = part
        elif part.startswith("hour="):
            hour = part[:7]
    return (day, hour, str(path))


def consume_tape(
    desk: DeskLoop,
    tape: Path,
    *,
    seen: Seen | None,
    extra_zones: tuple[Zone, ...] = (),
    now: datetime | None = None,
    cursor: TapeCursor | None = None,
) -> int:
    """Feed unseen parquet events into the loop. Second pass does not replay.

    With a `cursor` only changed files are parsed; without it (one-shot `--once`,
    old tests) the whole tape is loaded as before. `seen=None` (production) trusts
    the cursor's per-file offsets instead of a per-event set: a tuple per event for
    every event of two days is gigabytes.
    """
    fresh: list[MarketEvent] = []
    source = cursor.fresh_rows(tape, now=now) if cursor is not None else load_tape(tape)
    if seen is None:
        fresh = list(source)
    else:
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
    st = desk.state_for(event.symbol)
    live = card if card is not None else desk._card_for(event.symbol, event.exchange_ts)
    poc = _poc_from_card(live)
    when = event.exchange_ts
    local = when.astimezone(_MSK)
    key = (
        tuple((b.tf, b.close_ts) for b in st.bars),
        poc,
        when.date(),
        local.hour * 60 + local.minute >= 16 * 60 + 30,
        len(st.bars),
    )
    cached = desk.zone_cache.get(event.symbol)
    if cached is not None and cached[0] == key:
        return list(extra_zones) + list(cached[1])
    engine = ZoneEngine(tick_size=desk.tick_for(event.symbol), config=desk.config)
    built = engine.build(event.symbol, when, st.bars, poc=poc)
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
    """Close working TF first, then 1h / H4 / D1. Senior levels vote on the junior TF.

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
    tfs = desk.config.structure_tfs
    for tf in tfs:
        already = {b.open_ts for b in st.bars if b.tf == tf}
        for bar in closed_bars_from_trades(
            st.trades, symbol=symbol, tf=tf, now=now, already=already
        ):
            out.extend(desk.on_bar_close(bar))
    return out


def _close_due_bars(desk: DeskLoop, symbol: str, now: datetime) -> None:
    close_due_bars(desk, symbol, now)

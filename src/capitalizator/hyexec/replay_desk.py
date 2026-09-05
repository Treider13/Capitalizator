"""Replay recorded tape through the same desk into a sandbox userdir.

user_mode is learn: paper shadow writes, signer is never called, no demo/live send.
The clock is the last print of the hour (or 23:59:59Z), never wall now — a jump
to today would roll halts and time-stop papers against the wrong calendar.

Play is hour-by-hour so a book day is not one RAM list (VPS OOM 2026-09-03).
--from-day/--to-day keeps one desk across the range. After the last day, later
tape is followed while papers are open. hx_* holes are filled from trades.
No invented exit. Does not write infra/phase.yaml.
Contour A does not import this file.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.dataset import plan_from_rows
from capitalizator.hyexec.tape_day import iter_day_hours
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

# Paper max_hold is 6h (registry touch_pending_timeout_h). A few calendar days
# covers a weekend gap. We do not flatten what the tape has not closed.
FOLLOW_DAYS = 5
# Official orderbook.200: snapshot, then delta. A day that is only diffs is
# BookDirty until the last origin from the prior day is played. Same streams
# and hours as TapeCursor's production first pass — not a new window.
BOOK_STREAMS = ("snapshot", "resync", "book_diff", "bbo")


def clock_for(events: list[MarketEvent], day: str) -> datetime:
    """Last event on that day, else the last UTC second of the day. Never wall now."""
    if events:
        return max(event.exchange_ts for event in events)
    y, m, d = (int(part) for part in day.split("-"))
    return datetime(y, m, d, 23, 59, 59, tzinfo=UTC)


def next_day(day: str) -> str:
    y, m, d = (int(part) for part in day.split("-"))
    return (datetime(y, m, d, tzinfo=UTC) + timedelta(days=1)).date().isoformat()


def prev_day(day: str) -> str:
    y, m, d = (int(part) for part in day.split("-"))
    return (datetime(y, m, d, tzinfo=UTC) - timedelta(days=1)).date().isoformat()


def play_book_prelude(
    desk: DeskLoop,
    tape: Path,
    first_day: str,
    *,
    extra_zones: tuple[Zone, ...] = (),
) -> int:
    """Last BOOK_HOURS of book before the range. Diffs without this stay BookDirty."""
    from capitalizator.desk.tape import TapeCursor

    cur = first_day
    for _ in range(TapeCursor.RECENT_DAYS):
        cur = prev_day(cur)
        played = 0
        for hour in iter_day_hours(
            tape,
            cur,
            streams=BOOK_STREAMS,
            last=TapeCursor.BOOK_HOURS,
        ):
            desk.play(hour, extra_zones=extra_zones, now=clock_for(hour, cur))
            played += len(hour)
        if played:
            return played
    return 0


def days_between(start: str, end: str) -> list[str]:
    """Inclusive UTC dates. A missing --day used to be an error (month list OOM)."""
    if end < start:
        raise ValueError("to-day must be >= from-day")
    out = [start]
    while out[-1] < end:
        out.append(next_day(out[-1]))
    return out


def play_tape_day(
    desk: DeskLoop,
    tape: Path,
    day: str,
    *,
    extra_zones: tuple[Zone, ...] = (),
) -> tuple[int, datetime | None]:
    """Play one calendar day hour-by-hour. Does not load the whole book day."""
    n = 0
    last: datetime | None = None
    for hour in iter_day_hours(tape, day):
        last = clock_for(hour, day)
        desk.play(hour, extra_zones=extra_zones, now=last)
        n += len(hour)
    return n, last


def open_paper_n(desk: DeskLoop) -> int:
    return sum(1 for pos in desk.paper.positions.values() if pos.state in {"pending", "open"})


def follow_open_papers(
    desk: DeskLoop,
    tape: Path,
    day: str,
    *,
    extra_zones: tuple[Zone, ...] = (),
    bound: int = FOLLOW_DAYS,
) -> tuple[int, datetime | None]:
    """Play later tape days while papers are still open. Empty days do not invent exits."""
    followed = 0
    last: datetime | None = None
    cur = day
    while open_paper_n(desk) > 0 and followed < bound:
        cur = next_day(cur)
        followed += 1
        n, clock = play_tape_day(desk, tape, cur, extra_zones=extra_zones)
        if n == 0:
            continue
        last = clock
    return followed, last


def seed_sandbox(*, src: Any, dst: Any) -> dict[str, int]:
    """Copy venue facts the replay needs. Not journal, not paper, not user_mode."""
    n_inst = 0
    n_zones = 0
    raw = src.meta("instruments_snapshot") if src.available() else None
    if raw and dst.available():
        dst.set_meta("instruments_snapshot", raw)
        n_inst = 1
    if src.available() and dst.available():
        for row in src.list_zones():
            zid = str(row.get("zone_id") or "")
            if not zid:
                continue
            dst.put_zone(zid, row)
            n_zones += 1
    return {"instruments": n_inst, "zones": n_zones}


def zones_from_knowledge(knowledge: Any) -> tuple[Zone, ...]:
    """Stored map. load_pending only returns zones with a pending touch — replay needs all."""
    if knowledge is None or not knowledge.available():
        return ()
    from capitalizator.memory.revive import zone_from_payload

    out: list[Zone] = []
    for row in knowledge.list_zones():
        zone = zone_from_payload(row)
        if zone is not None:
            out.append(zone)
    return tuple(out)


def _backfill_after(knowledge: Any, tape: Path) -> int:
    from capitalizator.hyexec.backfill import backfill_knowledge, days_for_holes, needs_fill
    from capitalizator.hyexec.tape_day import load_trade_events

    rows = knowledge.journal_rows() if knowledge.available() else []
    holes = [row for row in rows if needs_fill(row)]
    if not holes:
        return 0
    symbols = {str(row.get("symbol") or "") for row in holes}
    symbols.discard("")
    days = days_for_holes(holes)
    events = (
        load_trade_events(tape, symbols=symbols, days=days or None)
        if symbols and tape.is_dir()
        else []
    )
    return int(backfill_knowledge(knowledge, events=events).get("filled") or 0)


def replay_days(
    *,
    tape: Path,
    knowledge: Any,
    days: list[str],
    now: datetime | None = None,
    extra_zones: tuple[Zone, ...] = (),
    follow_days: int = FOLLOW_DAYS,
) -> dict[str, Any]:
    if not days:
        raise ValueError("days must not be empty")
    desk = DeskLoop(knowledge=knowledge, user_mode="learn")
    stored = zones_from_knowledge(knowledge)
    extras = tuple(extra_zones) + stored
    for zone in extras:
        desk.registry._zones[zone.zone_id] = zone
    prelude = play_book_prelude(desk, tape, days[0], extra_zones=extras)
    n_events = 0
    last: datetime | None = None
    for day in days:
        n, clock = play_tape_day(desk, tape, day, extra_zones=extras)
        n_events += n
        if clock is not None:
            last = clock
    first = days[0]
    if now is not None and last is None:
        last = now
        desk.play((), extra_zones=extras, now=now)
    followed, follow_clock = follow_open_papers(
        desk, tape, days[-1], extra_zones=extras, bound=follow_days
    )
    when = now if now is not None else last or clock_for([], first)
    desk.tick(follow_clock or when, force_flush=True)
    filled = _backfill_after(knowledge, tape)
    rows = knowledge.journal_rows() if knowledge.available() else []
    plan = plan_from_rows(rows)
    plan["day"] = first
    plan["days"] = list(days)
    plan["n_events"] = n_events
    plan["n_prelude"] = prelude
    plan["n_followed"] = followed
    plan["n_open_paper"] = open_paper_n(desk)
    plan["n_zones"] = len(stored)
    plan["filled"] = filled
    plan["clock"] = when.isoformat()
    plan["user_mode"] = "learn"
    plan["sent"] = False
    return plan


def replay_day(
    *,
    tape: Path,
    knowledge: Any,
    day: str,
    now: datetime | None = None,
    extra_zones: tuple[Zone, ...] = (),
    follow_days: int = FOLLOW_DAYS,
) -> dict[str, Any]:
    return replay_days(
        tape=tape,
        knowledge=knowledge,
        days=[day],
        now=now,
        extra_zones=extra_zones,
        follow_days=follow_days,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay one tape day into a sandbox. No send.")
    parser.add_argument("--tape", required=True)
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--day", default="")
    parser.add_argument("--from-day", default="")
    parser.add_argument("--to-day", default="")
    parser.add_argument("--init", action="store_true")
    parser.add_argument(
        "--from-userdir",
        default="",
        help="Copy instruments_snapshot and zones from this vault. Not journal.",
    )
    args = parser.parse_args(argv)
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import init_vault, load_vault

    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    live = None
    try:
        seeded = {"instruments": 0, "zones": 0}
        if args.from_userdir:
            live = open_knowledge(load_vault(Path(args.from_userdir)), create=False)
            seeded = seed_sandbox(src=live, dst=knowledge)
        if args.from_day:
            days = days_between(args.from_day, args.to_day or args.from_day)
        elif args.day:
            days = [args.day]
        else:
            raise SystemExit("replay_desk needs --day or --from-day")
        plan = replay_days(
            tape=Path(args.tape),
            knowledge=knowledge,
            days=days,
        )
        plan["seeded"] = seeded
        print(json.dumps(plan, sort_keys=True))
        return 0
    finally:
        if live is not None:
            live.close()
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

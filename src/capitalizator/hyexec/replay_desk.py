"""Replay recorded tape through the same desk into a sandbox userdir.

user_mode is learn: paper shadow writes, signer is never called, no demo/live send.
The clock is the last print of the day (or 23:59:59Z), never wall now — a jump
to today would roll halts and time-stop papers against the wrong calendar.

One day often leaves papers open (r_net is written only on close). Subsequent
tape days are played until papers close or FOLLOW_DAYS is hit. No invented exit.

Does not write infra/phase.yaml. A missing --day is an error (month tape OOM).
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
from capitalizator.hyexec.tape_day import load_day_events
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

# Paper max_hold is 6h (registry touch_pending_timeout_h). A few calendar days
# covers a weekend gap. We do not flatten what the tape has not closed.
FOLLOW_DAYS = 5


def clock_for(events: list[MarketEvent], day: str) -> datetime:
    """Last event on that day, else the last UTC second of the day. Never wall now."""
    if events:
        return max(event.exchange_ts for event in events)
    y, m, d = (int(part) for part in day.split("-"))
    return datetime(y, m, d, 23, 59, 59, tzinfo=UTC)


def next_day(day: str) -> str:
    y, m, d = (int(part) for part in day.split("-"))
    return (datetime(y, m, d, tzinfo=UTC) + timedelta(days=1)).date().isoformat()


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
        more = load_day_events(tape, cur)
        followed += 1
        if not more:
            continue
        last = clock_for(more, cur)
        desk.play(more, extra_zones=extra_zones, now=last)
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


def replay_day(
    *,
    tape: Path,
    knowledge: Any,
    day: str,
    now: datetime | None = None,
    extra_zones: tuple[Zone, ...] = (),
    follow_days: int = FOLLOW_DAYS,
) -> dict[str, Any]:
    events = load_day_events(tape, day)
    desk = DeskLoop(knowledge=knowledge, user_mode="learn")
    stored = zones_from_knowledge(knowledge)
    extras = tuple(extra_zones) + stored
    for zone in extras:
        desk.registry._zones[zone.zone_id] = zone
    when = now if now is not None else clock_for(events, day)
    desk.play(events, extra_zones=extras, now=when)
    followed, follow_clock = follow_open_papers(
        desk, tape, day, extra_zones=extras, bound=follow_days
    )
    desk.tick(follow_clock or when, force_flush=True)
    rows = knowledge.journal_rows() if knowledge.available() else []
    plan = plan_from_rows(rows)
    plan["day"] = day
    plan["n_events"] = len(events)
    plan["n_followed"] = followed
    plan["n_open_paper"] = open_paper_n(desk)
    plan["n_zones"] = len(stored)
    plan["clock"] = when.isoformat()
    plan["user_mode"] = "learn"
    plan["sent"] = False
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay one tape day into a sandbox. No send.")
    parser.add_argument("--tape", required=True)
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--day", required=True)
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
        plan = replay_day(
            tape=Path(args.tape),
            knowledge=knowledge,
            day=args.day,
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

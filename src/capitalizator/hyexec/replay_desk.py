"""Replay one recorded day through the same desk into a sandbox userdir.

user_mode is learn: paper shadow writes, signer is never called, no demo/live send.
Does not write infra/phase.yaml. A missing --day is an error (month tape OOM).
Contour A does not import this file.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.dataset import plan_from_rows
from capitalizator.hyexec.tape_day import load_day_events
from capitalizator.zones.model import Zone


def replay_day(
    *,
    tape: Path,
    knowledge: Any,
    day: str,
    now: datetime,
    extra_zones: tuple[Zone, ...] = (),
) -> dict[str, Any]:
    events = load_day_events(tape, day)
    desk = DeskLoop(knowledge=knowledge, user_mode="learn")
    desk.play(events, extra_zones=extra_zones, now=now)
    desk.tick(now, force_flush=True)
    rows = knowledge.journal_rows() if knowledge.available() else []
    plan = plan_from_rows(rows)
    plan["day"] = day
    plan["n_events"] = len(events)
    plan["user_mode"] = "learn"
    plan["sent"] = False
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay one tape day into a sandbox. No send.")
    parser.add_argument("--tape", required=True)
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args(argv)
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import init_vault, load_vault

    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    try:
        now = datetime.now(tz=UTC)
        plan = replay_day(
            tape=Path(args.tape),
            knowledge=knowledge,
            day=args.day,
            now=now,
        )
        print(json.dumps(plan, sort_keys=True))
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

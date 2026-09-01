"""Contour B/C: night replay, overlay, daily report, fragility, card draft.

Does not send. Does not ask an LLM for a verdict. Replay uses recorded
frames only — missing tape is empty, not invented.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from capitalizator.card.draft import pending_card
from capitalizator.exec.replay import ReplayEngine
from capitalizator.memory.registry import Touch
from capitalizator.ops.daily_map_report import daily_map_report
from capitalizator.ops.knowledge import Knowledge
from capitalizator.types import MarketEvent, require_utc
from capitalizator.whales.fragility import forbid_new_long
from capitalizator.zones.model import Zone


def run_night(
    knowledge: Knowledge,
    *,
    day: str,
    now: datetime,
    replay_dir: Path | None = None,
    rows: Sequence[tuple[Zone, Touch]] = (),
    oi_events: list[MarketEvent] | None = None,
    funding_events: list[MarketEvent] | None = None,
    thin_book: bool | None = None,
    card_id: str = "night-draft",
) -> dict[str, Any]:
    require_utc(now)
    replayed = 0
    if replay_dir is not None and replay_dir.exists():
        book = replay_dir / "book.jsonl"
        if book.is_file() or replay_dir.is_file():
            ReplayEngine().run(replay_dir)
            replayed = 1
    body = daily_map_report(day=day, rows=rows)
    knowledge.save_report(day=day, kind="map", body=body)
    knowledge.put_overlay(f"{day}:shadow", r_shadow="0")
    oi_peak = None
    funding_top5 = None
    if oi_events:
        oi_peak = False
    if funding_events:
        funding_top5 = False
    fragile = forbid_new_long(
        oi_peak=oi_peak,
        funding_top5=funding_top5,
        thin_book=thin_book,
    )
    card = pending_card(
        thesis=f"night {day}",
        as_of=now,
        card_id=card_id,
        n_claims=5,
    )
    return {
        "day": day,
        "replayed": replayed,
        "report": body,
        "fragility": fragile,
        "card": card,
        "verdict": "pending",
    }


def main(argv: list[str] | None = None) -> int:
    """VPS cron: night replay + daily report + overlay. No LLM verdict. No send."""
    import argparse
    import json
    from datetime import UTC
    from pathlib import Path

    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import init_vault, load_vault

    parser = argparse.ArgumentParser(description="Night contour. No orders. No LLM verdict.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args(argv)
    vault = init_vault(Path(args.userdir)) if args.init else load_vault(Path(args.userdir))
    knowledge = open_knowledge(vault)
    try:
        out = run_night(
            knowledge,
            day=args.day,
            now=datetime.now(tz=UTC),
        )
        print(
            json.dumps(
                {
                    "day": out["day"],
                    "replayed": out["replayed"],
                    "fragility": out["fragility"],
                    "verdict": out["verdict"],
                    "n_claims": len(out["card"].claims),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

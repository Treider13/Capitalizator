"""Contour C night pass: facts of the day, no orders, no LLM verdict, nothing invented.

Once a day (00:30 UTC on the VPS, or by hand) over the desk's own knowledge:

  1. daily map report from the day's journal rows (touches / gestures) → `reports`;
  2. ShadowDay overlay: shadow / challenger / fade R of the day → `overlay`;
  3. class calibration snapshot from filled paper trades → meta `calibration_night`;
  4. the champion-vs-challenger exam, recorded (never promoting by itself) → meta `exam_night`;
  5. ОКО state summary: passports (n, mature), memory sizes, mirror → meta `oko_night`;
  6. author weights and intel source health as they stand → meta `intel_night`.

The old version "replayed" a directory and threw the result away, called the
fragility law with two unknown inputs (always False) and drafted a card of
`pending` claims. Those were placeholders and are gone.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from capitalizator.champion.calibrate import class_stats, to_meta
from capitalizator.champion.exam import exam
from capitalizator.champion.shadow_day import persist_day
from capitalizator.memory.registry import Touch
from capitalizator.memory.revive import (
    touch_record_from_journal,
    zone_from_journal,
    zone_from_payload,
)
from capitalizator.ops.daily_map_report import daily_map_report
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.settings import load_sources
from capitalizator.types import require_utc
from capitalizator.zones.model import Zone


def day_rows(knowledge: Knowledge, day: str) -> tuple[list[tuple[Zone, Touch]], list[str]]:
    """Every journal touch of the day as (zone, touch) — resolved or pending, on a live
    or a retired zone. The zone comes from the stored table when it is still there, else
    from the zone facts the desk writes into the row. Rows that carry neither are
    returned by id as `unplaced` (counted, never invented)."""
    if not knowledge.available():
        return [], []
    stored = {
        str(row.get("zone_id")): zone
        for row in knowledge.list_zones()
        if (zone := zone_from_payload(row)) is not None
    }
    out: list[tuple[Zone, Touch]] = []
    unplaced: list[str] = []
    seen: set[str] = set()
    for row in knowledge.journal_rows():
        ts = str(row.get("touch_ts") or "")
        if not ts.startswith(day):
            continue
        touch = touch_record_from_journal(row)
        if touch is None or touch.touch_id in seen:
            continue
        seen.add(touch.touch_id)
        zone = stored.get(touch.zone_id) or zone_from_journal(row)
        if zone is None:
            unplaced.append(touch.touch_id)
            continue
        out.append((zone, touch))
    out.sort(key=lambda pair: pair[1].ts)
    return out, unplaced


def _oko_summary(knowledge: Knowledge) -> dict[str, Any]:
    out: dict[str, Any] = {"passports": {}, "memory": {}, "mirror": None}
    for key, raw in knowledge.meta_prefix("oko:passport:").items():
        try:
            d = json.loads(raw)
            depth = d.get("depth") or []
            out["passports"][key.split(":", 2)[2]] = {
                "n": len(depth),
                "mature": len(depth) >= 30,
                "churn_n": len(d.get("churn") or []),
            }
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    for key, raw in knowledge.meta_prefix("oko:memory:").items():
        try:
            d = json.loads(raw)
            out["memory"][key.split(":", 2)[2]] = len(d.get("records") or [])
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    mirror = knowledge.meta("oko:mirror")
    if mirror:
        try:
            m = json.loads(mirror)
            out["mirror"] = {"passed": m.get("passed"), "at": m.get("at")}
        except json.JSONDecodeError:
            out["mirror"] = None
    return out


def run_night(knowledge: Knowledge, *, day: str, now: datetime) -> dict[str, Any]:
    when = require_utc(now)
    rows, unplaced = day_rows(knowledge, day)
    body = daily_map_report(day=day, rows=rows)
    if unplaced:
        body += f"\nКасаний без фактов зоны (не на карте): {len(unplaced)}.\n"
    knowledge.save_report(day=day, kind="map", body=body)
    snap = persist_day(knowledge, day)

    paper = knowledge.paper_trades(limit=200_000)
    stats = class_stats([p for p in paper if p.get("source") == "shadow"])
    knowledge.set_meta("calibration_night", to_meta(stats))

    report = exam(paper, now=when)
    knowledge.set_meta("exam_night", json.dumps(report.to_payload(), sort_keys=True))

    oko = _oko_summary(knowledge)
    knowledge.set_meta("oko_night", json.dumps({"at": when.isoformat(), **oko}, sort_keys=True))

    weights_raw = knowledge.meta("author_weights")
    intel = {
        "at": when.isoformat(),
        "sources": [
            {"id": s.get("id"), "enabled": s.get("enabled"), "last_ok": s.get("last_ok"),
             "last_error": s.get("last_error")}
            for s in load_sources(knowledge)
        ],
        "author_weights": json.loads(weights_raw) if weights_raw else None,
        "intel_items": len(knowledge.intel_items(limit=1_000_000)),
    }
    knowledge.set_meta("intel_night", json.dumps(intel, sort_keys=True, default=str))

    out = {
        "day": day,
        "n_rows": len(rows),
        "n_rows_unplaced": len(unplaced),
        "report": body,
        "n_shadow": snap.n_would,
        "r_shadow": None if snap.r_shadow is None else format(snap.r_shadow, "f"),
        "classes": len(stats),
        "exam_passed": report.passed,
        "exam_reasons": list(report.reasons),
        "oko": oko,
        "intel_sources": len(intel["sources"]),
    }
    # the console's «Управление» page shows the last night run without the report body
    knowledge.set_meta(
        "night_last",
        json.dumps({**{k: v for k, v in out.items() if k != "report"}, "at": when.isoformat()},
                   sort_keys=True, default=str),
    )
    return out


def main(argv: list[str] | None = None) -> int:
    """VPS: nightly facts of the day. No orders. No LLM verdict."""
    import argparse
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
        out = run_night(knowledge, day=args.day, now=datetime.now(tz=UTC))
        print(
            json.dumps(
                {k: out[k] for k in ("day", "n_rows", "n_shadow", "r_shadow", "classes",
                                      "exam_passed", "intel_sources")},
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

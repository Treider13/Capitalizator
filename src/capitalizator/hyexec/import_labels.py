"""Copy missing journal touches from a sandbox vault into the live one.

Does not overwrite a filled shadow r_net. Does not stamp a closed sandbox
shadow onto a live open paper_ids.shadow. Fills an empty shadow and hx_*
holes on the same touch_id. Does not send. Requires --ack.
Contour A does not import this file.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from capitalizator.champion.shadow_day import paper_r
from capitalizator.hyexec.backfill import apply_features
from capitalizator.hyexec.dataset import FEATURE_KEYS, plan_from_rows


def _shadow_open(row: dict[str, Any]) -> bool:
    ids = row.get("paper_ids")
    return isinstance(ids, dict) and bool(ids.get("shadow"))


def fill_holes(dest: dict[str, Any], src: dict[str, Any]) -> dict[str, Any] | None:
    """Copy sandbox shadow / hx_* into dest holes. None if dest is already full."""
    out = apply_features(dest, src)
    paper_changed = False
    if (
        not _shadow_open(dest)
        and paper_r(out, "shadow") is None
        and paper_r(src, "shadow") is not None
    ):
        src_paper = src.get("paper")
        if isinstance(src_paper, dict) and isinstance(src_paper.get("shadow"), dict):
            paper = dict(out["paper"]) if isinstance(out.get("paper"), dict) else {}
            paper["shadow"] = deepcopy(src_paper["shadow"])
            out["paper"] = paper
            paper_changed = True
    hx_changed = any(out.get(key) != dest.get(key) for key in (*FEATURE_KEYS, "hyexec_as_of"))
    if paper_changed or hx_changed:
        return out
    return None


def import_rows(
    *,
    source: list[dict[str, Any]],
    dest: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in dest:
        tid = str(row.get("touch_id") or "")
        if tid and tid not in by_id:
            by_id[tid] = dict(row)
    imported = 0
    filled = 0
    for row in source:
        tid = str(row.get("touch_id") or "")
        if not tid:
            continue
        if tid not in by_id:
            by_id[tid] = dict(row)
            imported += 1
            continue
        patched = fill_holes(by_id[tid], row)
        if patched is not None:
            by_id[tid] = patched
            filled += 1
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in dest:
        tid = str(row.get("touch_id") or "")
        if not tid:
            out.append(row)
            continue
        out.append(by_id[tid])
        seen.add(tid)
    for row in source:
        tid = str(row.get("touch_id") or "")
        if tid and tid not in seen:
            out.append(by_id[tid])
            seen.add(tid)
    return out, imported, filled


def import_vault(*, src: Any, dst: Any) -> dict[str, Any]:
    from capitalizator.ops.knowledge import open_knowledge

    source_k = open_knowledge(src)
    dest_k = open_knowledge(dst)
    try:
        incoming = source_k.journal_rows() if source_k.available() else []
        existing = dest_k.journal_rows() if dest_k.available() else []
        dest_map = {
            str(row.get("touch_id") or ""): row
            for row in existing
            if row.get("touch_id")
        }
        src_map = {
            str(row.get("touch_id") or ""): row
            for row in incoming
            if row.get("touch_id")
        }
        merged, n, filled = import_rows(source=incoming, dest=existing)
        if dest_k.available() and (n or filled):
            for row in merged:
                tid = str(row.get("touch_id") or "")
                if not tid:
                    continue
                if tid not in dest_map:
                    dest_k.put_journal_touch(tid, row)
                    continue
                src_row = src_map.get(tid)
                if src_row is not None and fill_holes(dest_map[tid], src_row) is not None:
                    dest_k.put_journal_touch(tid, row)
        plan = plan_from_rows(dest_k.journal_rows() if dest_k.available() else merged)
        plan["imported"] = n
        plan["filled"] = filled
        return plan
    finally:
        source_k.close()
        dest_k.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy missing journal rows from a sandbox. Requires --ack."
    )
    parser.add_argument("--from-userdir", required=True)
    parser.add_argument("--to-userdir", required=True)
    parser.add_argument("--ack", action="store_true")
    args = parser.parse_args(argv)
    if not args.ack:
        raise SystemExit("import_labels needs --ack (refuses to merge without it)")
    from capitalizator.ops.vault import load_vault

    plan = import_vault(
        src=load_vault(Path(args.from_userdir)),
        dst=load_vault(Path(args.to_userdir)),
    )
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

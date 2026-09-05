"""Copy missing journal touches from a sandbox vault into the live one.

Does not overwrite an existing touch_id. Does not send. Requires --ack.
Contour A does not import this file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from capitalizator.hyexec.dataset import plan_from_rows


def import_rows(
    *,
    source: list[dict[str, Any]],
    dest: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    have = {str(row.get("touch_id") or "") for row in dest}
    have.discard("")
    added: list[dict[str, Any]] = []
    for row in source:
        tid = str(row.get("touch_id") or "")
        if not tid or tid in have:
            continue
        added.append(dict(row))
        have.add(tid)
    return dest + added, len(added)


def import_vault(*, src: Any, dst: Any) -> dict[str, Any]:
    from capitalizator.ops.knowledge import open_knowledge

    source_k = open_knowledge(src)
    dest_k = open_knowledge(dst)
    try:
        incoming = source_k.journal_rows() if source_k.available() else []
        existing = dest_k.journal_rows() if dest_k.available() else []
        merged, n = import_rows(source=incoming, dest=existing)
        if n and dest_k.available():
            for row in merged:
                tid = str(row.get("touch_id") or "")
                if tid:
                    dest_k.put_journal_touch(tid, row)
        plan = plan_from_rows(dest_k.journal_rows() if dest_k.available() else merged)
        plan["imported"] = n
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

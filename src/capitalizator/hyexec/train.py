"""Train extra. Contour A never imports this file. xgboost stays behind the extra.

Opens the vault journal. n_complete < 15 → no fit. A label is not invented,
so xgboost.train is not called even when the exam window is full.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from capitalizator.hyexec.dataset import can_fit, complete_n


def plan_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = complete_n(rows)
    return {"n": n, "n_rows": len(rows), "fit": can_fit(n)}


def plan_from_userdir(userdir: Path) -> dict[str, Any]:
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import load_vault

    vault = load_vault(userdir)
    knowledge = open_knowledge(vault, create=False)
    try:
        rows = knowledge.journal_rows() if knowledge.available() else []
        return plan_from_rows(rows)
    finally:
        knowledge.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hyexec train. Requires the hyexec extra.")
    parser.add_argument("--userdir", required=True)
    args = parser.parse_args(argv)
    try:
        import xgboost  # noqa: F401
        from capitalizator.hyexec.river_adwin import drift_on  # noqa: F401
    except ImportError:
        raise SystemExit("hyexec extra missing: pip install -e '.[hyexec]'")
    plan = plan_from_userdir(Path(args.userdir))
    print(json.dumps(plan, sort_keys=True))
    # Complete rows are not a label. Do not call xgboost.train.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

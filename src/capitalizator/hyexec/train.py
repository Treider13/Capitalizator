"""Train extra. Contour A never imports this file. xgboost stays behind the extra.

Opens the vault journal. Fit only when ≥15 complete hx_* rows carry a filled
shadow r_net (the paper outcome, not an invented label). Then xgboost.train
writes hyexec_model.json into the vault.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from capitalizator.hyexec.dataset import labeled_pairs, plan_from_rows


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
        from capitalizator.hyexec.river_adwin import drift_on
    except ImportError:
        raise SystemExit("hyexec extra missing: pip install -e '.[hyexec]'")
    from capitalizator.hyexec.model import fit, save_booster
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import load_vault

    vault = load_vault(Path(args.userdir))
    knowledge = open_knowledge(vault, create=False)
    try:
        rows = knowledge.journal_rows() if knowledge.available() else []
        plan = plan_from_rows(rows)
        xs, ys = labeled_pairs(rows)
        plan["drift"] = bool(ys) and drift_on(ys)
        if not plan["fit"]:
            print(json.dumps(plan, sort_keys=True))
            return 0
        booster = fit(xs, ys)
        saved = save_booster(vault, booster)
        plan["saved"] = saved.name
        print(json.dumps(plan, sort_keys=True))
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

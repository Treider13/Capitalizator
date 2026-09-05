"""Train extra. Contour A never imports this file. xgboost stays behind the extra.

Opens the vault journal. First fit when ≥15 complete hx_* rows carry a filled
shadow r_net. Later fits only when river ADWIN flags a shift on *new* labels.
A timer never retrains.
"""

from __future__ import annotations

import argparse
import io
import json
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from capitalizator.hyexec.adwin import should_retrain, timer_retrain
from capitalizator.hyexec.dataset import labeled_events, plan_from_rows
from capitalizator.hyexec.model import fit, load_booster, save_booster

ADWIN_NAME = "hyexec_adwin.joblib"
IDLE_S = 5.0
SLICE_S = 0.05
_tried_holes: dict[str, tuple[str, ...]] = {}


def stop_on_signals() -> Callable[[], bool]:
    stopped = False

    def handle(signum: int, frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)
    return lambda: stopped


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


def _load_detector(vault: Any) -> tuple[object | None, list[str]]:
    import joblib

    path = vault.knowledge / ADWIN_NAME
    if not path.is_file():
        return None, []
    raw = joblib.load(path)
    if not isinstance(raw, dict):
        return None, []
    seen = raw.get("ids")
    if not isinstance(seen, list):
        seen = []
    return raw.get("det"), [str(x) for x in seen]


def _save_detector(vault: Any, det: object | None, ids: list[str]) -> None:
    import joblib

    from capitalizator.ops.vault import write_regular_bytes

    buf = io.BytesIO()
    joblib.dump({"det": det, "ids": list(ids)}, buf)
    write_regular_bytes(vault.knowledge / ADWIN_NAME, buf.getvalue())


def tick(vault: Any, knowledge: Any) -> dict[str, Any]:
    from capitalizator.hyexec.backfill import backfill_knowledge, days_for_holes, needs_fill
    from capitalizator.hyexec.river_adwin import push
    from capitalizator.hyexec.tape_day import load_trade_events

    rows = knowledge.journal_rows() if knowledge.available() else []
    filled = 0
    holes = [row for row in rows if needs_fill(row)]
    hole_key = tuple(sorted(str(row.get("touch_id") or "") for row in holes if row.get("touch_id")))
    vault_id = str(getattr(vault, "root", "") or id(vault))
    if holes and hole_key != _tried_holes.get(vault_id):
        symbols = {str(row.get("symbol") or "") for row in holes}
        symbols.discard("")
        events = []
        tape = getattr(vault, "tape", None)
        if symbols and tape is not None and Path(tape).is_dir():
            events = load_trade_events(
                Path(tape), symbols=symbols, days=days_for_holes(holes) or None
            )
        filled = int(backfill_knowledge(knowledge, events=events).get("filled") or 0)
        _tried_holes[vault_id] = hole_key
        rows = knowledge.journal_rows() if knowledge.available() else rows
    plan = plan_from_rows(rows)
    plan["filled"] = filled
    events = labeled_events(rows)
    xs = [e[1] for e in events]
    ys = [e[2] for e in events]
    have = load_booster(vault) is not None
    det, seen = _load_detector(vault)
    seen_set = set(seen)
    new = [y for tid, _x, y in events if tid not in seen_set]
    drifted = False
    if new:
        drifted, det = push(new, detector=det)
        seen = [tid for tid, _x, _y in events]
        _save_detector(vault, det, seen)
    plan["drift"] = drifted
    plan["timer"] = timer_retrain(hours=24)
    want = (not have and plan["fit"]) or (
        have and plan["fit"] and should_retrain(adwin_drift=drifted)
    )
    if not want:
        plan["saved"] = None
        return plan
    booster = fit(xs, ys)
    saved = save_booster(vault, booster)
    _save_detector(vault, None, [tid for tid, _x, _y in events])
    plan["saved"] = saved.name
    return plan


def train_loop(
    *,
    userdir: Path,
    should_stop: Callable[[], bool],
    idle_s: float = IDLE_S,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import load_vault

    vault = load_vault(userdir)
    knowledge = open_knowledge(vault, create=False)
    ticks = 0
    try:
        while not should_stop():
            tick(vault, knowledge)
            ticks += 1
            if idle_s <= 0:
                break
            end = time.monotonic() + idle_s
            while not should_stop() and time.monotonic() < end:
                remain = end - time.monotonic()
                if remain <= 0:
                    break
                sleep(min(SLICE_S, remain))
    finally:
        knowledge.close()
    return ticks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hyexec train. Requires the hyexec extra.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        import xgboost  # noqa: F401
        from capitalizator.hyexec.river_adwin import drift_on  # noqa: F401
    except ImportError:
        raise SystemExit("hyexec extra missing: pip install -e '.[hyexec]'")
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import load_vault

    if args.once:
        vault = load_vault(Path(args.userdir))
        knowledge = open_knowledge(vault, create=False)
        try:
            plan = tick(vault, knowledge)
            print(json.dumps(plan, sort_keys=True))
        finally:
            knowledge.close()
        return 0
    train_loop(userdir=Path(args.userdir), should_stop=stop_on_signals())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

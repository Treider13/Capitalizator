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
from capitalizator.hyexec.dataset import labeled_pairs, plan_from_rows
from capitalizator.hyexec.model import fit, load_booster, model_path, save_booster

ADWIN_NAME = "hyexec_adwin.joblib"
IDLE_S = 5.0
SLICE_S = 0.05


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


def _load_detector(vault: Any) -> tuple[object | None, int]:
    import joblib

    path = vault.knowledge / ADWIN_NAME
    if not path.is_file():
        return None, 0
    raw = joblib.load(path)
    if not isinstance(raw, dict):
        return None, 0
    return raw.get("det"), int(raw.get("n") or 0)


def _save_detector(vault: Any, det: object | None, n: int) -> None:
    import joblib

    from capitalizator.ops.vault import write_regular_bytes

    buf = io.BytesIO()
    joblib.dump({"det": det, "n": n}, buf)
    write_regular_bytes(vault.knowledge / ADWIN_NAME, buf.getvalue())


def tick(vault: Any, knowledge: Any) -> dict[str, Any]:
    from capitalizator.hyexec.river_adwin import push

    rows = knowledge.journal_rows() if knowledge.available() else []
    plan = plan_from_rows(rows)
    xs, ys = labeled_pairs(rows)
    have = load_booster(vault) is not None
    det, seen = _load_detector(vault)
    new = ys[seen:]
    drifted = False
    if new:
        drifted, det = push(new, detector=det)
        seen = len(ys)
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
    _save_detector(vault, None, len(ys))
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

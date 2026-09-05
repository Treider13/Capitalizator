"""Live hyexec process: timing facts only. Does not import xgboost. Does not send."""

from __future__ import annotations

import argparse
import json
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.hyexec.dataset import last_complete, plan_from_rows
from capitalizator.hyexec.model import load_booster, model_go, predict_one

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


def tick(knowledge: Any, *, now: datetime, vault: Any | None = None) -> dict[str, Any]:
    """Score the latest complete PIT row when a booster exists. Else model_go is None."""
    rows = knowledge.journal_rows() if knowledge.available() else []
    plan = plan_from_rows(rows)
    score = None
    go = None
    loaded = False
    if vault is not None:
        booster = load_booster(vault)
        vec = last_complete(rows)
        if booster is not None:
            loaded = True
        if booster is not None and vec is not None:
            score = predict_one(booster, vec)
            go = model_go(score)
    body = {
        "as_of": now.isoformat(),
        "model": loaded,
        "model_go": go,
        "score": score,
        **plan,
    }
    if knowledge.available():
        knowledge.set_meta("hyexec_serve", json.dumps(body, sort_keys=True))
    return body


def serve_loop(
    *,
    userdir: Path,
    should_stop: Callable[[], bool],
    idle_s: float = IDLE_S,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> int:
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import load_vault

    vault = load_vault(userdir)
    knowledge = open_knowledge(vault, create=True)
    ticks = 0
    try:
        while not should_stop():
            when = now if now is not None else datetime.now(tz=UTC)
            tick(knowledge, now=when, vault=vault)
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
    parser = argparse.ArgumentParser(description="hyexec timing loop. No orders.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.once:
        from capitalizator.ops.knowledge import open_knowledge
        from capitalizator.ops.vault import load_vault

        vault = load_vault(Path(args.userdir))
        knowledge = open_knowledge(vault, create=True)
        try:
            body = tick(knowledge, now=datetime.now(tz=UTC), vault=vault)
            print(json.dumps(body, sort_keys=True))
        finally:
            knowledge.close()
        return 0
    serve_loop(userdir=Path(args.userdir), should_stop=stop_on_signals())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

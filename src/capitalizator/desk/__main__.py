"""Desk process: read tape / events, write sqlite. No keys. No signer."""

from __future__ import annotations

import argparse
import json
import signal
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.desk.tape import TapeCursor, consume_tape
from capitalizator.news_macro.ingest import load_desk_calendar
from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.product import read_user_mode
from capitalizator.ops.vault import Vault, init_vault, load_vault
from capitalizator.screener.universe import load_desk_universe
from capitalizator.zones.model import Zone


def stop_on_signals() -> Callable[[], bool]:
    """SIGINT / SIGTERM flip a flag. The serve loop exits on the next idle."""
    stopped = False

    def handle(signum: int, frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)
    return lambda: stopped


def run_once(
    *,
    vault: Vault,
    knowledge: Knowledge,
    now: datetime | None = None,
    extra_zones: Sequence[Zone] = (),
) -> DeskLoop:
    """One pass over the parquet tape. No sleep. Used by `--once` and tests."""
    desk = DeskLoop(
        knowledge=knowledge,
        user_mode=read_user_mode(vault),
        calendar=load_desk_calendar(),
    )
    when = now if now is not None else datetime.now(tz=UTC)
    consume_tape(desk, vault.tape, seen=set(), extra_zones=tuple(extra_zones), now=when)
    return desk


def serve_loop(
    *,
    vault: Vault,
    knowledge: Knowledge,
    should_stop: Callable[[], bool],
    idle_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    on_tick: Callable[[DeskLoop], None] | None = None,
    now: datetime | None = None,
    extra_zones: Sequence[Zone] = (),
) -> DeskLoop:
    """Stay up. Read parquet tape, tick ZLG, re-read user_mode. No invented rows."""
    desk = DeskLoop(
        knowledge=knowledge,
        user_mode=read_user_mode(vault),
        calendar=load_desk_calendar(),
    )
    seen: set[tuple[str, str, str, int | None]] = set()
    zones = tuple(extra_zones)
    cursor = TapeCursor()
    while not should_stop():
        desk.user_mode = read_user_mode(vault)
        if desk.user_mode in {"demo", "live"}:
            desk.strategy.desk_mode = desk.user_mode
        else:
            desk.strategy.desk_mode = "off"
        when = now if now is not None else datetime.now(tz=UTC)
        consume_tape(desk, vault.tape, seen=seen, extra_zones=zones, now=when, cursor=cursor)
        desk.tick(when)
        if on_tick is not None:
            on_tick(desk)
        if idle_s:
            sleep(idle_s)
    return desk


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Desk orchestrator. No keys.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    try:
        mode = read_user_mode(vault)
        payload = {
            "process": "desk",
            "user_mode": mode,
            "n_symbols": len(load_desk_universe().symbols),
            "has_key": False,
        }
        if args.once:
            desk = run_once(vault=vault, knowledge=knowledge)
            print(
                json.dumps(
                    {
                        **payload,
                        "once": True,
                        "n_touches": len(desk.registry.touches),
                        "n_shadow": len(desk.shadow_writes),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if not args.serve:
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        print(json.dumps({**payload, "serve": True}, ensure_ascii=False), flush=True)
        serve_loop(vault=vault, knowledge=knowledge, should_stop=stop_on_signals())
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

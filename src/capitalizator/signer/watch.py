"""External dead-man. Reads signer_heartbeat from SQLite. Cancel is injected.

If signer is SIGKILL'd, this process still fires cancel_all.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import sleep as _sleep

from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.product import read_user_mode
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.signer.process import HEARTBEAT_S, META_HEARTBEAT
from capitalizator.types import require_utc

WATCH_STALE_S = HEARTBEAT_S * 3


def _parse_beat(raw: str | None) -> datetime | None:
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    when = datetime.fromisoformat(text)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return require_utc(when)


def watcher_tick(
    knowledge: Knowledge,
    cancel_all: Callable[[], None],
    *,
    now: datetime,
    stale_s: int = WATCH_STALE_S,
) -> bool:
    """True when cancel_all ran. Missing or old heartbeat is stale."""
    when = require_utc(now)
    last = _parse_beat(knowledge.meta(META_HEARTBEAT))
    if last is None or (when - last).total_seconds() > stale_s:
        cancel_all()
        return True
    return False


def exchange_cancel_all(vault) -> str:
    """Re-read mode. off/learn still cancel testnet leftovers after SIGKILL."""
    from capitalizator.exchange.client import ExchangeClient

    mode = read_user_mode(vault)
    client = ExchangeClient.from_vault(vault)
    if mode == "live":
        client.cancel_all(user_mode="live")
        return "live"
    client.cancel_all(user_mode="demo")
    return "demo"


def serve_watch(
    *,
    knowledge: Knowledge,
    cancel_all: Callable[[], None],
    should_stop: Callable[[], bool],
    idle_s: float = 1.0,
    now: datetime | None = None,
    sleep: Callable[[float], None] = _sleep,
) -> None:
    while not should_stop():
        when = now if now is not None else datetime.now(tz=UTC)
        watcher_tick(knowledge, cancel_all, now=when)
        if idle_s:
            sleep(idle_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signer watcher. cancel_all if heartbeat dies.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    try:
        fired = {"n": 0}
        host_mode = {"v": None}

        def cancel() -> None:
            fired["n"] += 1
            try:
                host_mode["v"] = exchange_cancel_all(vault)
            except Exception:
                host_mode["v"] = None

        if args.once or not args.serve:
            stale = watcher_tick(knowledge, cancel, now=datetime.now(tz=UTC))
            print(
                json.dumps(
                    {
                        "process": "watcher",
                        "stale": stale,
                        "cancelled": fired["n"],
                        "host_mode": host_mode["v"],
                        "stale_s": WATCH_STALE_S,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        print(
            json.dumps({"process": "watcher", "serve": True, "stale_s": WATCH_STALE_S}, ensure_ascii=False),
            flush=True,
        )
        serve_watch(knowledge=knowledge, cancel_all=cancel, should_stop=lambda: False)
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

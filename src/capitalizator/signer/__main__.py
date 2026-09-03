"""Signer process: only process with a key. Heartbeat 30s, reconcile 60s.

With keys (environment or vault secrets file — see gateway/keys.py) the loop
is the real gateway loop: watchdog, intent drain to Bybit via pybit, OMS drain,
reconcile, exchange state for the console. Without keys the drain keeps the
`{"status": "not_sent"}` stub and prints `"gateway": "absent"` — nothing pretends.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.gateway.keys import PAPER_MODES
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import read_user_mode
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.signer.process import (
    HEARTBEAT_S,
    RECONCILE_S,
    drain_validated,
    gateway_mode_ok,
    make_watchdogs,
    on_signer_exit,
    serve_gateway_loop,
    serve_loop,
)


def build_gateway(vault):  # type: ignore[no-untyped-def]
    """(gateway, tracker, feed) or (None, None, None) when no key is configured."""
    from capitalizator.gateway import BybitGateway, PositionTracker, load_keys
    from capitalizator.gateway.bybit import make_session
    from capitalizator.gateway.ws import PrivateFeed, make_private_ws

    keys = load_keys(vault)
    if keys is None:
        return None, None, None
    gateway = BybitGateway(make_session(keys), mode=keys.mode)
    tracker = PositionTracker()
    feed = PrivateFeed(tracker, ws=make_private_ws(keys))
    return gateway, tracker, feed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signer. Key never in desk.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--hello", action="store_true", help="prove the key step by step")
    parser.add_argument(
        "--probe-order", action="store_true", help="hello: place+cancel a far order"
    )
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    cancels: list[int] = []
    try:
        gateway, tracker, feed = build_gateway(vault)
        mode = read_user_mode(vault)
        payload = {
            "process": "signer",
            "heartbeat_s": HEARTBEAT_S,
            "reconcile_s": RECONCILE_S,
            "user_mode": mode,
            "gateway": "absent" if gateway is None else gateway.mode,
        }
        if args.hello:
            if gateway is None:
                print(json.dumps({**payload, "hello": {"ok": False, "error": "no keys"}}))
                return 2
            result = gateway.hello(probe_order=args.probe_order)
            from capitalizator.ops.product import mark_hello

            mark_hello(vault, ok=bool(result.get("ok")))
            knowledge.set_meta("hello_result", json.dumps(result, default=str))
            print(json.dumps({**payload, "hello": result}, ensure_ascii=False, default=str))
            return 0 if result.get("ok") else 1
        if gateway is None:
            dead, _recon = make_watchdogs(
                cancel_all=lambda: cancels.append(1),
                dead_man_s=HEARTBEAT_S,
                reconcile_s=RECONCILE_S,
            )
            if args.once or not args.serve:
                if mode in {"demo", "live"}:
                    drain_validated(
                        knowledge,
                        lambda row: {"status": "not_sent"},
                        user_mode=mode,
                        now=datetime.now(tz=UTC),
                    )
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            print(json.dumps({**payload, "serve": True}, ensure_ascii=False), flush=True)
            serve_loop(
                knowledge=knowledge,
                vault=vault,
                send=lambda row: {"status": "not_sent"},
                cancel_all=lambda: cancels.append(1),
                should_stop=lambda: False,
            )
            return 0
        if args.once or not args.serve:
            if mode in {"demo", "live"}:
                if not gateway_mode_ok(mode, gateway.mode):
                    print(json.dumps({**payload, "error": "user mode / key mode mismatch"}))
                    return 3
                venue = gateway.mode if gateway.mode in PAPER_MODES else "demo"
                drain_validated(
                    knowledge, gateway.send, user_mode=mode, now=datetime.now(tz=UTC), venue=venue
                )
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        print(json.dumps({**payload, "serve": True}, ensure_ascii=False), flush=True)
        serve_gateway_loop(
            knowledge=knowledge,
            vault=vault,
            gateway=gateway,
            tracker=tracker,
            feed=feed,
            should_stop=lambda: False,
        )
        return 0
    finally:
        on_signer_exit(lambda: cancels.append(1))
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

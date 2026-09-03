"""Signer process: the only process with a key. Heartbeat / reconcile from time.yaml.

With keys (environment or vault secrets file — see gateway/keys.py) the loop is
the real gateway loop: watchdog, intent drain to Bybit via pybit, OMS drain,
reconcile, exchange state for the console. Without keys pending intents are
parked as `no_gateway` and the process prints `"gateway": "absent"` — nothing
pretends, and the desk keeps its ideas for when a key appears.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import read_user_mode, record_hello
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.signer.process import (
    HEARTBEAT_S,
    RECONCILE_S,
    alerter_from_settings,
    drain_once,
    drain_validated,
    gateway_mode_ok,
    on_signer_exit,
    park_no_gateway,
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
    gateway = None
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
            ok = record_hello(vault, knowledge, result)
            print(json.dumps({**payload, "hello": result}, ensure_ascii=False, default=str))
            return 0 if ok else 1
        if gateway is None:
            if args.once or not args.serve:
                if mode in {"demo", "live"}:
                    drain_once(
                        knowledge, park_no_gateway, user_mode=mode, now=datetime.now(tz=UTC)
                    )
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            print(json.dumps({**payload, "serve": True}, ensure_ascii=False), flush=True)
            serve_loop(knowledge=knowledge, vault=vault, should_stop=lambda: False)
            return 0
        if args.once or not args.serve:
            blocked = json.loads(knowledge.meta("entries_blocked") or "[]")
            if mode in {"demo", "live"}:
                if not gateway_mode_ok(mode, gateway.mode):
                    print(json.dumps({**payload, "error": "user mode / key mode mismatch"}))
                    return 3
                if not blocked:
                    venue = gateway.mode  # the order carries the venue the key really talks to
                    drain_validated(
                        knowledge,
                        gateway.send,
                        user_mode=mode,
                        now=datetime.now(tz=UTC),
                        venue=venue,
                    )
            print(json.dumps({**payload, "entries_blocked": blocked}, ensure_ascii=False))
            return 0
        print(json.dumps({**payload, "serve": True}, ensure_ascii=False), flush=True)
        try:
            serve_gateway_loop(
                knowledge=knowledge,
                vault=vault,
                gateway=gateway,
                tracker=tracker,
                feed=feed,
                should_stop=lambda: False,
                alerter=alerter_from_settings(vault),
            )
        finally:
            # Only the serving process owns resting entries: when IT goes, no entry may
            # survive it. `--hello` / `--once` are inspections and cancel nothing (audit A4).
            on_signer_exit(lambda: _cancel_quiet(gateway))
        return 0
    finally:
        knowledge.close()


def _cancel_quiet(gateway) -> None:  # type: ignore[no-untyped-def]
    try:
        gateway.cancel_entries(None, reason="signer_exit")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())

"""Signer process: only process with a key. Heartbeat 30s, reconcile 60s."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.exchange.client import ExchangeError
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import hello_recorded, mark_hello, read_user_mode
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.signer.process import (
    HEARTBEAT_S,
    RECONCILE_S,
    drain_validated,
    make_watchdogs,
    on_signer_exit,
    serve_loop,
)


def _trade_mode(vault) -> str:
    mode = read_user_mode(vault)
    return mode if mode in {"demo", "live"} else "demo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signer. Key never in desk.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--hello", action="store_true")
    parser.add_argument("--mid", default=None, help="mid for testnet hello (else public ticker)")
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    client = None
    cancels: list[int] = []
    try:
        dead, _recon = make_watchdogs(
            cancel_all=lambda: cancels.append(1),
            dead_man_s=HEARTBEAT_S,
            reconcile_s=RECONCILE_S,
        )
        mode = read_user_mode(vault)
        payload: dict = {
            "process": "signer",
            "heartbeat_s": dead.dead_man_s,
            "reconcile_s": RECONCILE_S,
            "user_mode": mode,
            "hello_ok": hello_recorded(vault),
        }
        if args.serve or args.hello:
            from capitalizator.exchange.client import (
                ExchangeClient,
                public_mid,
                require_withdraw_off,
                testnet_hello,
            )

            client = ExchangeClient.from_vault(vault)
            require_withdraw_off(client, user_mode=_trade_mode(vault))
            if args.hello or not hello_recorded(vault):
                mid = Decimal(str(args.mid)) if args.mid else public_mid(client.http)
                testnet_hello(client, mid=mid)
                mark_hello(vault, ok=True)
                payload["hello_ok"] = True
                payload["hello"] = "ok"

        def send(row: dict) -> dict:
            if client is None:
                return {"status": "not_sent"}
            return client.send_order(row, user_mode=_trade_mode(vault))

        def cancel_all() -> None:
            cancels.append(1)
            if client is not None:
                client.cancel_all(user_mode=_trade_mode(vault))

        if args.once or not args.serve:
            if mode in {"demo", "live"}:
                drain_validated(
                    knowledge,
                    send,
                    user_mode=mode,
                    now=datetime.now(tz=UTC),
                )
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        print(json.dumps({**payload, "serve": True}, ensure_ascii=False), flush=True)
        serve_loop(
            knowledge=knowledge,
            vault=vault,
            send=send,
            cancel_all=cancel_all,
            should_stop=lambda: False,
        )
        return 0
    except ExchangeError as exc:
        print(json.dumps({"process": "signer", "error": str(exc)}, ensure_ascii=False))
        return 2
    finally:
        def _exit_cancel() -> None:
            cancels.append(1)
            if client is not None:
                client.cancel_all(user_mode=_trade_mode(vault))

        on_signer_exit(_exit_cancel)
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

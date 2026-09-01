"""Signer process: only process with a key. Heartbeat 30s, reconcile 60s."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import read_user_mode
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.signer.process import (
    HEARTBEAT_S,
    RECONCILE_S,
    drain_validated,
    make_watchdogs,
    on_signer_exit,
    serve_loop,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signer. Key never in desk.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    cancels: list[int] = []
    try:
        dead, _recon = make_watchdogs(
            cancel_all=lambda: cancels.append(1),
            dead_man_s=HEARTBEAT_S,
            reconcile_s=RECONCILE_S,
        )
        mode = read_user_mode(vault)
        payload = {
            "process": "signer",
            "heartbeat_s": dead.dead_man_s,
            "reconcile_s": RECONCILE_S,
            "user_mode": mode,
        }
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
    finally:
        on_signer_exit(lambda: cancels.append(1))
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

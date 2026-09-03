"""Signer process: only process with a cred file. Heartbeat 30s, reconcile 60s."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, read_user_mode
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.signer.bybit_rest import MAIN_HOST, cancel_open, submit_limit
from capitalizator.signer.cred import default_cred_file, load_cred
from capitalizator.signer.process import (
    HEARTBEAT_S,
    RECONCILE_S,
    drain_validated,
    make_watchdogs,
    on_signer_exit,
    serve_loop,
)


def _has_cred(path: Path | None) -> bool:
    return path is not None and path.is_file() and not path.is_symlink()


def build_send(cred_path: Path | None, *, vault) -> object:
    """live + cred file → mainnet. Reloads the file each send so Chronos can write it."""

    def send(row: dict) -> dict:
        mode = read_user_mode(vault)
        if mode != "live":
            return {"status": "not_sent", "reason": "not_live"}
        if cred_path is None or not _has_cred(cred_path):
            raise ValueError("live needs cred file")
        cred = load_cred(cred_path)
        if str(row.get("trading_mode") or "") != "mainnet":
            raise ValueError("live sends mainnet only")
        return submit_limit(cred, row, host=MAIN_HOST)

    return send


def build_cancel(cred_path: Path | None, *, vault, sink: list[int]) -> object:
    def cancel() -> None:
        sink.append(1)
        if cred_path is None or not _has_cred(cred_path):
            return
        if read_user_mode(vault) != "live":
            return
        cancel_open(load_cred(cred_path), host=MAIN_HOST)

    return cancel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signer. Key never in desk.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cred-file", default=None)
    parser.add_argument("--mark-hello", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    if args.mark_hello:
        mark_hello(vault, ok=True)
    knowledge = open_knowledge(vault)
    cred_path = Path(args.cred_file) if args.cred_file else default_cred_file(vault.root)
    cancels: list[int] = []
    send = build_send(cred_path, vault=vault)
    cancel = build_cancel(cred_path, vault=vault, sink=cancels)
    try:
        dead, _recon = make_watchdogs(
            cancel_all=cancel,
            dead_man_s=HEARTBEAT_S,
            reconcile_s=RECONCILE_S,
        )
        mode = read_user_mode(vault)
        ready = _has_cred(cred_path)
        payload = {
            "process": "signer",
            "heartbeat_s": dead.dead_man_s,
            "reconcile_s": RECONCILE_S,
            "user_mode": mode,
            "has_cred": ready,
            "send": "mainnet" if mode == "live" and ready else "not_sent",
        }
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
            cancel_all=cancel,
            should_stop=lambda: False,
        )
        return 0
    finally:
        on_signer_exit(cancel)
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""Desk process: read tape / events, write sqlite. No keys. No signer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import read_user_mode
from capitalizator.ops.vault import init_vault, load_vault
from capitalizator.screener.universe import load_desk_universe


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
        desk = DeskLoop(knowledge=knowledge, user_mode=mode)
        payload = {
            "process": "desk",
            "user_mode": desk.user_mode,
            "n_symbols": len(load_desk_universe().symbols),
            "has_key": False,
        }
        if args.once or not args.serve:
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        print(json.dumps({**payload, "serve": True}, ensure_ascii=False))
        return 0
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())

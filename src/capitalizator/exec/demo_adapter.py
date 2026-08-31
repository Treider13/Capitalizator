"""1.5.5 — paper path to the testnet signer. No mainnet host. No send.

trading_mode must be demo. Current infra/phase.yaml is off → reject.
Does not call Bybit. episode.mode=demo only when the mode is demo and
the signer accepted the schema; status is not_sent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from capitalizator.signer.validate import Signer, UnsignedIntent


def _phase_mode() -> str:
    root = Path(__file__).resolve()
    for parent in root.parents:
        candidate = parent / "infra" / "phase.yaml"
        if candidate.is_file():
            raw = yaml.safe_load(candidate.read_text(encoding="utf-8"))
            return str((raw or {}).get("trading_mode") or "off")
    return "off"


class DemoAdapter:
    def __init__(self, *, trading_mode: str | None = None, signer: Signer | None = None) -> None:
        self.trading_mode = trading_mode if trading_mode is not None else _phase_mode()
        self.signer = signer or Signer()

    def submit(self, unsigned: UnsignedIntent) -> dict[str, Any]:
        if self.trading_mode != "demo":
            raise ValueError(f"trading_mode={self.trading_mode!r} is not demo; not sending")
        if unsigned.trading_mode != "testnet":
            raise ValueError("demo adapter talks to testnet signer only")
        order = self.signer.validate(unsigned)
        return {
            "mode": "demo",
            "status": "not_sent",
            "symbol": order.symbol,
            "stop_px": str(order.stop_px),
        }

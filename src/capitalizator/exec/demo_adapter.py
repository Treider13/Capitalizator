"""1.5.5 — paper path to the testnet signer. No mainnet host. No send.

trading_mode must be demo. Current infra/phase.yaml is off → reject.
Does not call Bybit. episode.mode=demo only when the mode is demo and
the signer accepted the schema; status is not_sent.
"""

from __future__ import annotations

from typing import Any

from capitalizator.ops.phase import trading_mode as phase_trading_mode
from capitalizator.signer.validate import Signer, UnsignedIntent


class DemoAdapter:
    def __init__(self, *, trading_mode: str | None = None, signer: Signer | None = None) -> None:
        self.trading_mode = trading_mode if trading_mode is not None else phase_trading_mode()
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

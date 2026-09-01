"""1.5.5 — paper path to the testnet signer. No mainnet host.

trading_mode must be demo. Current infra/phase.yaml is off → reject.
Default submit is {status: not_sent}. A real POST is only the injected
`post` callable (testnet hello / signer process). Host is never hardcoded.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from capitalizator.ops.phase import trading_mode as phase_trading_mode
from capitalizator.signer.validate import Order, Signer, UnsignedIntent

PostFn = Callable[[Order], dict[str, Any]]


class DemoAdapter:
    def __init__(
        self,
        *,
        trading_mode: str | None = None,
        signer: Signer | None = None,
        post: PostFn | None = None,
    ) -> None:
        self.trading_mode = trading_mode if trading_mode is not None else phase_trading_mode()
        self.signer = signer or Signer()
        self._post = post

    def submit(self, unsigned: UnsignedIntent) -> dict[str, Any]:
        if self.trading_mode != "demo":
            raise ValueError(f"trading_mode={self.trading_mode!r} is not demo; not sending")
        if unsigned.trading_mode != "testnet":
            raise ValueError("demo adapter talks to testnet signer only")
        order = self.signer.validate(unsigned)
        if self._post is None:
            return {
                "mode": "demo",
                "status": "not_sent",
                "symbol": order.symbol,
                "stop_px": str(order.stop_px),
            }
        result = self._post(order)
        status = str(result.get("status") or "sent")
        return {
            "mode": "demo",
            "status": status,
            "symbol": order.symbol,
            "stop_px": str(order.stop_px),
            "exchange": result,
        }

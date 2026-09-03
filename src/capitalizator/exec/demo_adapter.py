"""1.5.5 — paper path to the paper-venue signer. No mainnet host.

trading_mode must be demo. Current infra/phase.yaml is off → reject.
Default submit is {status: not_sent}. A real POST is only the injected
`post` callable (Demo Trading / testnet hello or the signer process). Host is never
hardcoded; the unsigned intent names its paper venue (demo | testnet).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from capitalizator.ops.phase import trading_mode as phase_trading_mode
from capitalizator.signer.validate import PAPER_VENUES, Order, Signer, UnsignedIntent

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
        if unsigned.trading_mode not in PAPER_VENUES:
            raise ValueError("demo adapter talks to a paper venue (demo|testnet) only")
        order = self.signer.validate(unsigned)
        if self._post is None:
            return {
                "mode": "demo",
                "venue": order.trading_mode,
                "status": "not_sent",
                "symbol": order.symbol,
                "stop_px": str(order.stop_px),
            }
        result = self._post(order)
        status = str(result.get("status") or "sent")
        return {
            "mode": "demo",
            "venue": order.trading_mode,
            "status": status,
            "symbol": order.symbol,
            "stop_px": str(order.stop_px),
            "exchange": result,
        }

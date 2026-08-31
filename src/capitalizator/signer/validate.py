"""0.4.4 — unsigned intent → paper order. Testnet only. No key. No send.

Week-0 whitelist is BTCUSDT/ETHUSDT. Mainnet mode is rejected.
This does not place a testnet order.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from capitalizator.screener.universe import Universe, default_week0_path, load_universe

Side = Literal["buy", "sell"]


class UnsignedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Side
    qty: Decimal
    limit_px: Decimal
    stop_px: Decimal
    trading_mode: Literal["testnet"]


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Side
    qty: Decimal
    limit_px: Decimal
    stop_px: Decimal
    trading_mode: Literal["testnet"]


class Signer:
    def __init__(self, universe: Universe | None = None) -> None:
        self.universe = universe or load_universe(default_week0_path())

    def validate(self, unsigned: UnsignedIntent) -> Order:
        if unsigned.trading_mode != "testnet":
            raise ValueError("signer accepts testnet only")
        if unsigned.symbol not in self.universe.symbols:
            raise ValueError(f"symbol not in week0 universe: {unsigned.symbol}")
        if unsigned.qty <= 0 or unsigned.limit_px <= 0 or unsigned.stop_px <= 0:
            raise ValueError("qty/limit/stop must be > 0")
        if unsigned.side == "buy" and unsigned.stop_px >= unsigned.limit_px:
            raise ValueError("buy stop must be below limit")
        if unsigned.side == "sell" and unsigned.stop_px <= unsigned.limit_px:
            raise ValueError("sell stop must be above limit")
        return Order(
            symbol=unsigned.symbol,
            side=unsigned.side,
            qty=unsigned.qty,
            limit_px=unsigned.limit_px,
            stop_px=unsigned.stop_px,
            trading_mode="testnet",
        )

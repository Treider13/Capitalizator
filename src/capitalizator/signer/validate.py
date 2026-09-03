"""Unsigned intent → order. Testnet or mainnet venue. No key. No HTTP.

Week-0 whitelist is the isolated default (BTCUSDT/ETHUSDT).
Desk drain uses the 24-symbol universe. Stop is mandatory.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from capitalizator.screener.universe import Universe, default_week0_path, load_universe

Side = Literal["buy", "sell"]
Venue = Literal["testnet", "mainnet"]


class UnsignedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Side
    qty: Decimal
    limit_px: Decimal
    stop_px: Decimal
    tp_px: Decimal | None = None
    reduce_only_stop: bool = True
    trading_mode: Venue


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Side
    qty: Decimal
    limit_px: Decimal
    stop_px: Decimal
    tp_px: Decimal | None = None
    reduce_only_stop: bool = True
    trading_mode: Venue


class Signer:
    def __init__(self, universe: Universe | None = None) -> None:
        self.universe = universe or load_universe(default_week0_path())

    def validate(self, unsigned: UnsignedIntent) -> Order:
        if unsigned.trading_mode not in {"testnet", "mainnet"}:
            raise ValueError("trading_mode must be testnet or mainnet")
        if unsigned.symbol not in self.universe.symbols:
            raise ValueError(f"symbol not in week0 universe: {unsigned.symbol}")
        if unsigned.qty <= 0 or unsigned.limit_px <= 0 or unsigned.stop_px <= 0:
            raise ValueError("qty/limit/stop must be > 0")
        if unsigned.side == "buy" and unsigned.stop_px >= unsigned.limit_px:
            raise ValueError("buy stop must be below limit")
        if unsigned.side == "sell" and unsigned.stop_px <= unsigned.limit_px:
            raise ValueError("sell stop must be above limit")
        if not unsigned.reduce_only_stop:
            raise ValueError("stop must be reduce-only")
        return Order(
            symbol=unsigned.symbol,
            side=unsigned.side,
            qty=unsigned.qty,
            limit_px=unsigned.limit_px,
            stop_px=unsigned.stop_px,
            tp_px=unsigned.tp_px,
            reduce_only_stop=True,
            trading_mode=unsigned.trading_mode,
        )

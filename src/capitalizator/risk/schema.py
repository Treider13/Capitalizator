"""Risk actions. Averaging / pyramid / martingale cannot be represented."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FORBIDDEN_ACTIONS = frozenset(
    {
        "average_in",
        "add_to_position",
        "pyramid",
        "martingale",
        "add_to_existing",
        "dca",
        "grid_add",
    }
)

RiskAction = Literal["accept", "cut_size", "reject"]
ManageAction = Literal["reduce", "flatten", "trail"]
Side = Literal["buy", "sell"]


def reject_forbidden_keys(raw: dict[str, Any]) -> None:
    keys = set(raw)
    if "action" in raw and raw["action"] in FORBIDDEN_ACTIONS:
        raise ValueError(f"forbidden action: {raw['action']}")
    if "manage" in raw and raw["manage"] in FORBIDDEN_ACTIONS:
        raise ValueError(f"forbidden manage: {raw['manage']}")
    hit = keys & FORBIDDEN_ACTIONS
    if hit:
        raise ValueError(f"forbidden fields: {sorted(hit)}")
    nested = raw.get("average_in")
    if nested is not None:
        raise ValueError("forbidden field: average_in")


class Intent(BaseModel):
    """Single new idea. Second fill of the same idea is not a field here."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Side
    entry: Decimal
    stop: Decimal
    tp: Decimal
    tag: str
    qty: Decimal | None = None
    size_mult: Decimal = Field(default=Decimal("1"))
    # D-16: leverage is part of the trade, not an ambient constant.
    lev: Decimal | None = None
    # Which operator risk config sized this intent (risk/config.py).
    risk_config_id: str | None = None
    # D-38: the gateway refuses an intent after this exchange time (stale price).
    valid_until: str | None = None

    @field_validator("symbol")
    @classmethod
    def _symbol_ok(cls, value: str) -> str:
        if not value.endswith("USDT") and not value.endswith("USDC"):
            raise ValueError("symbol must be a linear perp quote")
        return value


class RiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: RiskAction
    reason: str = ""
    size_mult: Decimal = Field(default=Decimal("1"))


class ManageIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ManageAction
    fraction: Decimal | None = None


class Position(Intent):
    """Single open idea. Spec 1.5.3 name. Same fields as Intent. No add-to."""


class RiskEngine:
    """Validates intents. One open idea per symbol, `max_open` in total.
    Does not place orders. No averaging (a second open on the same symbol raises)."""

    def __init__(self, *, max_open: int = 1) -> None:
        if max_open < 1:
            raise ValueError("max_open must be >= 1")
        self.max_open = max_open
        self._open: dict[str, Position] = {}

    @property
    def _open_position(self) -> Position | None:
        """Legacy single-position view (spec 1.5.3)."""
        return next(iter(self._open.values()), None)

    def open_positions(self) -> list[Position]:
        return list(self._open.values())

    def validate(self, intent: Intent | dict[str, Any]) -> Intent:
        if isinstance(intent, dict):
            reject_forbidden_keys(intent)
            return Intent.model_validate(intent)
        return intent

    def allow_entry(self, symbol: str | None = None) -> bool:
        if symbol is not None and symbol in self._open:
            return False
        return len(self._open) < self.max_open

    def on_open(self, intent: Intent | dict[str, Any]) -> Position:
        parsed = self.validate(intent)
        if parsed.symbol in self._open:
            raise ValueError("already in a position")  # add-to is not a field here
        if len(self._open) >= self.max_open:
            raise ValueError("already in a position")
        pos = Position.model_validate(parsed.model_dump())
        self._open[parsed.symbol] = pos
        return pos

    def on_flat(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._open.clear()
            return
        self._open.pop(symbol, None)

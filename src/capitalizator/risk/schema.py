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
    """Validates intents. One open idea. Does not place orders. No averaging."""

    def __init__(self) -> None:
        self._open_position: Position | None = None

    def validate(self, intent: Intent | dict[str, Any]) -> Intent:
        if isinstance(intent, dict):
            reject_forbidden_keys(intent)
            return Intent.model_validate(intent)
        return intent

    def allow_entry(self) -> bool:
        return self._open_position is None

    def on_open(self, intent: Intent | dict[str, Any]) -> Position:
        parsed = self.validate(intent)
        if self._open_position is not None:
            raise ValueError("already in a position")
        self._open_position = Position.model_validate(parsed.model_dump())
        return self._open_position

    def on_flat(self) -> None:
        self._open_position = None

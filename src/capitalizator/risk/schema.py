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


class RiskEngine:
    """Validates intents. Does not place orders. Cannot accept averaging."""

    def validate(self, intent: Intent | dict[str, Any]) -> Intent:
        if isinstance(intent, dict):
            reject_forbidden_keys(intent)
            return Intent.model_validate(intent)
        return intent

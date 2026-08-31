"""Saved-R ledger. Shadow only: R not burned because a veto/skip fired.

PHASE-BUILD: not live PnL. Empty total is None, not a fake zero.
A bounce skip that later breaks = +1R saved. A bounce skip that later
bounces = missed, not profit. Die = 0. Does not open size.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

Reason = Literal[
    "SILENCE",
    "SPLIT",
    "VETO",
    "CPI",
    "no_verified",
    "first_minute",
    "mid_range",
    "btc_break",
    "wall_no_print",
]
Outcome = Literal["bounce", "break", "die"]
REASONS = frozenset(
    {
        "SILENCE",
        "SPLIT",
        "VETO",
        "CPI",
        "no_verified",
        "first_minute",
        "mid_range",
        "btc_break",
        "wall_no_print",
    }
)
R_UNIT = Decimal("1")


@dataclass(frozen=True)
class SavedRow:
    zone_id: str
    reason: Reason
    idea: str
    outcome: Outcome | None
    saved_r: Decimal | None
    missed_r: Decimal | None


class SavedLedger:
    def __init__(self) -> None:
        self.rows: list[SavedRow] = []

    def record(self, *, zone_id: str, reason: Reason, idea: str = "bounce") -> SavedRow:
        if not zone_id:
            raise ValueError("zone_id is empty")
        if reason not in REASONS:
            raise ValueError(f"unknown skip reason: {reason!r}")
        if idea != "bounce":
            raise ValueError("only bounce idea is scored in F1")
        row = SavedRow(
            zone_id=zone_id,
            reason=reason,
            idea=idea,
            outcome=None,
            saved_r=None,
            missed_r=None,
        )
        self.rows.append(row)
        return row

    def resolve(self, *, zone_id: str, outcome: Outcome) -> SavedRow:
        if outcome not in {"bounce", "break", "die"}:
            raise ValueError(f"unknown outcome: {outcome!r}")
        for i, row in enumerate(self.rows):
            if row.zone_id == zone_id and row.outcome is None:
                saved, missed = _score(row.idea, outcome)
                done = replace(row, outcome=outcome, saved_r=saved, missed_r=missed)
                self.rows[i] = done
                return done
        raise KeyError(zone_id)

    def total_saved(self) -> Decimal | None:
        done = [row.saved_r for row in self.rows if row.saved_r is not None]
        if not done:
            return None
        return sum(done, Decimal("0"))

    def total_missed(self) -> Decimal | None:
        done = [row.missed_r for row in self.rows if row.missed_r is not None]
        if not done:
            return None
        return sum(done, Decimal("0"))


def _score(idea: str, outcome: Outcome) -> tuple[Decimal, Decimal]:
    if outcome == "die":
        return Decimal("0"), Decimal("0")
    if idea == "bounce" and outcome == "break":
        return R_UNIT, Decimal("0")
    if idea == "bounce" and outcome == "bounce":
        return Decimal("0"), R_UNIT
    return Decimal("0"), Decimal("0")

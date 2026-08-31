"""Percent-Time Frontier. ρ = E[R] × risk% / hours the class occupied.

INVENTION-JURY / PHASE-BUILD: this is the only % race we may run.
It is not a world PnL rank. n<20 → ρ unknown. n<139 → cannot pick a class.
Does not raise account risk to inflate ρ.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

F1_RISK = Decimal("0.01")
POST_GATE_RISK = Decimal("0.012")
N_MIN_RHO = 20
N_MIN_PICK = 139
WINDOW_H = Decimal("3")


@dataclass(frozen=True)
class ClassStat:
    class_id: str
    n: int
    avg_r: Decimal
    hours: Decimal


@dataclass(frozen=True)
class PtfRow:
    class_id: str
    n: int
    avg_r: Decimal
    hours: Decimal
    risk_frac: Decimal
    rho: Decimal | None
    pickable: bool


def rho(avg_r: Decimal, risk_frac: Decimal, hours: Decimal) -> Decimal:
    if hours <= 0 or risk_frac <= 0:
        raise ValueError("hours and risk_frac must be > 0")
    return avg_r * risk_frac / hours


class PtfTable:
    def evaluate(
        self,
        stat: ClassStat,
        *,
        risk_frac: Decimal = F1_RISK,
        gate_passed: bool = False,
    ) -> PtfRow:
        if stat.n < 0:
            raise ValueError("n must be >= 0")
        if stat.hours > WINDOW_H:
            raise ValueError("class hours cannot exceed the 3h session window")
        cap = POST_GATE_RISK if gate_passed else F1_RISK
        if risk_frac > cap:
            raise ValueError("PTF cannot raise risk to inflate rho")
        got = None if stat.n < N_MIN_RHO else rho(stat.avg_r, risk_frac, stat.hours)
        return PtfRow(
            class_id=stat.class_id,
            n=stat.n,
            avg_r=stat.avg_r,
            hours=stat.hours,
            risk_frac=risk_frac,
            rho=got,
            pickable=stat.n >= N_MIN_PICK and got is not None,
        )

    def pick(self, rows: list[PtfRow]) -> str | None:
        ready = [row for row in rows if row.pickable and row.rho is not None]
        if not ready:
            return None
        return max(ready, key=lambda row: row.rho or Decimal("0")).class_id

    def world_return_rank(self) -> None:
        """FIRST-IN-WORLD: we do not hold a global % title. Always None."""
        return None

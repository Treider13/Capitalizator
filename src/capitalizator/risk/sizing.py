"""1.5.1 — margin from target risk. Does not place an order.

risk% = margin% × lev × stop%.
raw_margin = target_risk / (lev × stop_frac).
If raw > 10% equity cap → reject (do not raise lev). F1 max lev = 3.

PHASE-BUILD artifact: Sizing.compute(equity, lev, stop_frac, target_risk).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Action = Literal["accept", "reject"]
CAP_MARGIN = Decimal("0.10")
F1_TARGET = Decimal("0.01")
F1_MAX_LEV = Decimal("3")


@dataclass(frozen=True)
class SizeDecision:
    action: Action
    reason: str
    margin_frac: Decimal | None
    account_risk: Decimal | None
    lev: Decimal


def implied_risk(*, margin_frac: Decimal, lev: Decimal, stop_frac: Decimal) -> Decimal:
    if margin_frac <= 0 or lev <= 0 or stop_frac <= 0:
        raise ValueError("margin/lev/stop must be > 0")
    return margin_frac * lev * stop_frac


class Sizer:
    def __init__(
        self,
        *,
        target_risk: Decimal = F1_TARGET,
        max_lev: Decimal = F1_MAX_LEV,
        cap_margin: Decimal = CAP_MARGIN,
    ) -> None:
        if target_risk <= 0 or max_lev <= 0 or cap_margin <= 0:
            raise ValueError("risk knobs must be > 0")
        self.target_risk = target_risk
        self.max_lev = max_lev
        self.cap_margin = cap_margin

    def decide(
        self,
        *,
        lev: Decimal,
        stop_frac: Decimal,
        requested_margin: Decimal | None = None,
    ) -> SizeDecision:
        if stop_frac <= 0:
            raise ValueError("stop_frac must be > 0")
        if lev > self.max_lev:
            return SizeDecision(
                action="reject",
                reason="lev above F1 max 3x",
                margin_frac=None,
                account_risk=None,
                lev=lev,
            )
        raw = self.target_risk / (lev * stop_frac)
        if raw > self.cap_margin:
            return SizeDecision(
                action="reject",
                reason="стоп слишком широк для 10% и этого плеча",
                margin_frac=None,
                account_risk=None,
                lev=lev,
            )
        if requested_margin is not None:
            risk = implied_risk(margin_frac=requested_margin, lev=lev, stop_frac=stop_frac)
            if risk > self.target_risk:
                return SizeDecision(
                    action="reject",
                    reason="requested margin would exceed target risk",
                    margin_frac=None,
                    account_risk=risk,
                    lev=lev,
                )
        return SizeDecision(
            action="accept",
            reason="ok",
            margin_frac=raw,
            account_risk=self.target_risk,
            lev=lev,
        )

    def compute(
        self,
        equity: Decimal,
        lev: Decimal,
        stop_frac: Decimal,
        target_risk: Decimal | None = None,
    ) -> SizeDecision:
        """Spec name. Cap is 10% of this equity. Does not raise lev."""
        if equity <= 0:
            raise ValueError("equity must be > 0")
        target = self.target_risk if target_risk is None else target_risk
        if target <= 0:
            raise ValueError("target_risk must be > 0")
        if stop_frac <= 0:
            raise ValueError("stop_frac must be > 0")
        if lev > self.max_lev:
            return SizeDecision(
                action="reject",
                reason="lev above F1 max 3x",
                margin_frac=None,
                account_risk=None,
                lev=lev,
            )
        cap_abs = self.cap_margin * equity
        raw_abs = (target * equity) / (lev * stop_frac)
        if raw_abs > cap_abs:
            return SizeDecision(
                action="reject",
                reason="стоп слишком широк для 10% и этого плеча",
                margin_frac=None,
                account_risk=None,
                lev=lev,
            )
        return SizeDecision(
            action="accept",
            reason="ok",
            margin_frac=raw_abs / equity,
            account_risk=target,
            lev=lev,
        )


Sizing = Sizer

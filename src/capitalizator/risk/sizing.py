"""1.5.1 — margin from target risk. Does not place an order.

risk% = margin% × lev × stop%.
raw_margin = target_risk / (lev × stop_frac).
If raw > 10% equity cap → reject (do not raise lev). F1 max lev = 3.

B `cut_size` is applied in proposer (`exec/strategy_bounce.propose`):
it shrinks Intent.size_mult. Sizer only accepts or rejects; it does not
cut size.

PHASE-BUILD artifact: Sizing.compute(equity, lev, stop_frac, target_risk).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
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


@dataclass(frozen=True)
class QtyDecision:
    action: Action
    reason: str
    qty: Decimal
    lev: Decimal
    margin: Decimal
    risk_usdt: Decimal
    risk_frac: Decimal
    binding: str  # target_risk | deposit_share | cap_margin | min_qty | min_notional


def size_position(
    *,
    equity: Decimal,
    entry: Decimal,
    stop: Decimal,
    lev: Decimal,
    target_risk: Decimal,
    deposit_share: Decimal,
    qty_step: Decimal,
    min_qty: Decimal,
    min_notional: Decimal,
    cap_margin: Decimal = CAP_MARGIN,
    max_lev: Decimal = F1_MAX_LEV,
) -> QtyDecision:
    """Concrete qty from equity, stop distance and the two operator knobs (D-11/D-12).

    qty_risk   = target_risk × equity / |entry − stop|     (risk budget)
    qty_margin = deposit_share × equity × lev / entry     (margin the operator allows)
    qty_cap    = cap_margin × equity × lev / entry        (10% margin hard cap)
    qty = min of the three, floored to qty_step. Leverage is never raised to fit.
    Below min_qty / min_notional → reject (no "0.001 anyway").
    """
    if equity <= 0 or entry <= 0 or stop <= 0:
        raise ValueError("equity/entry/stop must be > 0")
    if lev <= 0:
        raise ValueError("lev must be > 0")
    if qty_step <= 0 or min_qty <= 0:
        raise ValueError("qty_step/min_qty must be > 0")
    if lev > max_lev:
        return QtyDecision(
            "reject", f"lev {lev} above max {max_lev}", Decimal("0"), lev,
            Decimal("0"), Decimal("0"), Decimal("0"), "max_lev",
        )
    dist = abs(entry - stop)
    if dist <= 0:
        raise ValueError("stop must differ from entry")
    qty_risk = target_risk * equity / dist
    qty_margin = deposit_share * equity * lev / entry
    qty_cap = cap_margin * equity * lev / entry
    candidates = {
        "target_risk": qty_risk,
        "deposit_share": qty_margin,
        "cap_margin": qty_cap,
    }
    binding = min(candidates, key=lambda k: candidates[k])
    raw = candidates[binding]
    qty = (raw / qty_step).to_integral_value(rounding=ROUND_DOWN) * qty_step
    margin = qty * entry / lev
    risk_usdt = qty * dist
    risk_frac = risk_usdt / equity
    if qty < min_qty:
        return QtyDecision(
            "reject", f"qty {qty} < minOrderQty {min_qty}", qty, lev, margin,
            risk_usdt, risk_frac, "min_qty",
        )
    if qty * entry < min_notional:
        return QtyDecision(
            "reject", f"notional {qty * entry} < minNotional {min_notional}", qty, lev,
            margin, risk_usdt, risk_frac, "min_notional",
        )
    return QtyDecision("accept", "ok", qty, lev, margin, risk_usdt, risk_frac, binding)

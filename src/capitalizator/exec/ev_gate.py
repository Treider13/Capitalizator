"""EV gate: a winning trade must stay a winning trade after costs (D-06).

Audit: with 2-tick zones on BTC one R was 0.9 USDT/coin while the maker
round-trip was 44 R — every 3R "win" lost money. Nothing compared fees with the
actual R; the screener compared them with a hard-coded 1% "typical move".

Rule (fee_multiple_min is an operator knob, default 5 — nof1/Alpha Arena 2025:
"PnL was dominated by trading costs"; FINAL-SYSTEM §5: fees ≈5% of the risk
budget is tolerable):

    costs      = fees_round_trip(notional) + expected_funding(hold) + slippage
    r_gross    = qty × |entry − stop|
    ok  iff    r_gross ≥ fee_multiple_min × costs
    r_net(k)   = k × r_gross − costs          (reported for k = 1, 2, 3)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from capitalizator.exec.fees import FeeTable, Role


@dataclass(frozen=True)
class EvDecision:
    ok: bool
    reason: str
    r_gross: Decimal
    fees: Decimal
    funding: Decimal
    slippage: Decimal
    costs: Decimal
    fee_multiple: Decimal | None  # r_gross / costs
    r_net_1r: Decimal
    r_net_2r: Decimal
    r_net_3r: Decimal
    breakeven_winrate: Decimal | None  # p such that p·(2R_gross − c) = (1−p)·(R_gross + c)


def expected_funding(
    *,
    notional: Decimal,
    funding_rate: Decimal | None,
    hold_hours: Decimal,
    interval_min: int,
) -> Decimal:
    """Funding paid over the expected hold if the position is on the paying side.

    Sign is dropped: we charge the cost whenever a payment is due in the window
    (direction of the position vs. rate sign is not known at intent time).
    """
    if funding_rate is None or hold_hours <= 0 or interval_min <= 0:
        return Decimal("0")
    settlements = (hold_hours * 60) / Decimal(interval_min)
    settlements = settlements.to_integral_value(rounding="ROUND_CEILING")
    return notional * abs(funding_rate) * settlements


def evaluate(
    *,
    qty: Decimal,
    entry: Decimal,
    stop: Decimal,
    tick: Decimal,
    role: Role = "maker",
    fees: FeeTable | None = None,
    funding_rate: Decimal | None = None,
    hold_hours: Decimal = Decimal("2"),
    funding_interval_min: int = 480,
    slippage_ticks: int = 1,
    fee_multiple_min: Decimal = Decimal("5"),
) -> EvDecision:
    if qty <= 0 or entry <= 0 or stop <= 0 or tick <= 0:
        raise ValueError("qty/entry/stop/tick must be > 0")
    if fee_multiple_min < 1:
        raise ValueError("fee_multiple_min must be >= 1")
    table = fees or FeeTable()
    notional = qty * entry
    fee = table.round_trip(notional, role=role)
    fund = expected_funding(
        notional=notional,
        funding_rate=funding_rate,
        hold_hours=hold_hours,
        interval_min=funding_interval_min,
    )
    slip = qty * tick * slippage_ticks
    costs = fee + fund + slip
    r_gross = qty * abs(entry - stop)
    if r_gross <= 0:
        raise ValueError("stop must differ from entry")
    multiple = None if costs == 0 else r_gross / costs
    r1 = r_gross - costs
    r2 = 2 * r_gross - costs
    r3 = 3 * r_gross - costs
    # p·(2R−c) − (1−p)·(R+c) = 0  →  p = (R + c) / (3R)
    denom = 3 * r_gross
    breakeven = (r_gross + costs) / denom if denom > 0 else None
    ok = multiple is not None and multiple >= fee_multiple_min or costs == 0
    reason = "ok"
    if not ok:
        reason = f"fee_gt_r: 1R={r_gross} costs={costs} multiple={multiple}"
    return EvDecision(
        ok=bool(ok),
        reason=reason,
        r_gross=r_gross,
        fees=fee,
        funding=fund,
        slippage=slip,
        costs=costs,
        fee_multiple=multiple,
        r_net_1r=r1,
        r_net_2r=r2,
        r_net_3r=r3,
        breakeven_winrate=breakeven,
    )

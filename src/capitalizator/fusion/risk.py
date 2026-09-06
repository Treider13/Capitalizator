"""Account-wide risk constraints. Reservation and outbox insert share one transaction."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from capitalizator.fusion.config import Config
from capitalizator.fusion.contracts import Contract
from capitalizator.fusion.store import Store, encode

ACTIVE = ("pending", "sending", "unknown", "accepted", "partial", "filled", "cancelling")


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick: float
    step: float
    minimum: float
    min_notional: float
    max_qty: float
    max_leverage: float
    maker: float
    taker: float
    funding_minutes: int

    def __post_init__(self) -> None:
        for name in ("tick", "step", "minimum", "max_qty", "max_leverage", "funding_minutes"):
            if not 0 < getattr(self, name) < math.inf:
                raise ValueError(f"invalid instrument {name}")
        if not all(math.isfinite(v) for v in (self.maker, self.taker, self.min_notional)):
            raise ValueError("nonfinite fees or notional")
        if self.taker < 0 or self.min_notional < 0 or self.minimum > self.max_qty:
            raise ValueError("invalid instrument limits")

    @classmethod
    def parse(cls, row: dict[str, Any], fees: tuple[float, float]) -> Instrument:
        lots = row["lotSizeFilter"]
        return cls(
            str(row["symbol"]),
            float(row["priceFilter"]["tickSize"]),
            float(lots["qtyStep"]),
            float(lots["minOrderQty"]),
            float(lots.get("minNotionalValue", 0)),
            min(float(lots["maxOrderQty"]), float(lots.get("maxMktOrderQty", lots["maxOrderQty"]))),
            float(row["leverageFilter"]["maxLeverage"]),
            *fees,
            int(row.get("fundingInterval", 480)),
        )


def floor_step(value: float, step: float) -> float:
    return float(
        (Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)
        * Decimal(str(step))
    )


def position_risk(row: dict[str, Any]) -> float:
    qty = float(row.get("size") or 0)
    if not qty:
        return 0.0
    mark = float(row.get("markPrice") or row.get("avgPrice") or 0)
    stop = float(row.get("stopLoss") or 0)
    if mark <= 0 or stop <= 0:
        return math.inf
    # Floating profit is not an exemption from the daily mark-to-market budget.
    return qty * (abs(mark - stop) + mark * 0.002)


def reserve(
    store: Store,
    mode: str,
    contract: Contract,
    instrument: Instrument,
    config: Config,
    at: float,
    entry: float,
    depth: float,
    spread: float,
    funding: float,
    fraction: float = 1.0,
) -> tuple[dict[str, Any] | None, str]:
    if mode not in {"demo", "live"}:
        raise ValueError("mode must be demo or live")
    if not 0 < fraction <= 1:
        raise ValueError("risk multiplier may only reduce")
    if not all(math.isfinite(v) for v in (entry, depth, spread, funding)):
        return None, "nonfinite_market"
    side = contract.side
    entry = floor_step(entry, instrument.tick)
    stop = floor_step(contract.invalidation, instrument.tick)
    if entry <= 0 or stop <= 0 or side * (entry - stop) <= 0:
        return None, "invalid_stop"
    if side * (contract.target - entry) < config.minimum_rr * abs(entry - stop):
        return None, "reward_after_confirmation"
    leverage = min(config.leverage, instrument.max_leverage)
    # Conservative margin distance check; actual risk tiers and venue liquidation
    # price are additionally checked after fills by the executor.
    if abs(entry - stop) / entry + 0.02 >= 1 / leverage:
        return None, "stop_near_liquidation"
    funding_cost = (
        abs(funding) * entry * max(1, config.max_hold_s / (instrument.funding_minutes * 60))
    )
    unit_loss = abs(entry - stop) + entry * (instrument.taker * 2) + spread * 2 + funding_cost
    costs = unit_loss - abs(entry - stop)
    if side * (contract.target - entry) - costs < config.minimum_rr * unit_loss:
        return None, "net_reward_after_costs"
    ident = "acr-" + contract.id
    with store.transaction() as db:
        state = db.execute("SELECT state FROM contracts WHERE id=?", (contract.id,)).fetchone()
        if state is None or state["state"] != "confirmed" or at >= contract.expires:
            return None, "contract_not_active"
        if db.execute("SELECT 1 FROM orders WHERE id=?", (ident,)).fetchone():
            return None, "already_reserved"
        account = db.execute("SELECT * FROM account WHERE mode=?", (mode,)).fetchone()
        if not account or at - account["at"] > config.account_age_s:
            return None, "account_stale"
        body = json.loads(account["body"])
        positions = [p for p in body["positions"] if float(p.get("size") or 0) > 0]
        venue_orders = body["orders"]
        if any(
            not str(o.get("orderLinkId") or "").startswith("acr-")
            and not o.get("reduceOnly")
            and not o.get("closeOnTrigger")
            for o in venue_orders
        ):
            return None, "unmanaged_venue_order"
        rows = db.execute(
            "SELECT * FROM orders WHERE mode=? AND state IN "
            "('pending','sending','unknown','accepted','partial','filled','cancelling')",
            (mode,),
        ).fetchall()
        by_symbol: dict[str, float] = {}
        margins: dict[str, float] = {}
        for row in rows:
            by_symbol[row["symbol"]] = by_symbol.get(row["symbol"], 0) + row["reserve"]
            spec = json.loads(row["body"])
            margins[row["symbol"]] = margins.get(row["symbol"], 0) + (
                float(spec["qty"]) * float(spec["price"]) / float(spec["leverage"])
            )
        for pos in positions:
            if int(pos.get("positionIdx") or 0) != 0:
                return None, "hedge_mode_not_supported"
            by_symbol[pos["symbol"]] = max(by_symbol.get(pos["symbol"], 0), position_risk(pos))
            position_margin = float(pos.get("positionIM") or 0)
            if not position_margin:
                position_margin = (
                    float(pos["size"])
                    * float(pos.get("markPrice") or pos["avgPrice"])
                    / max(1.0, float(pos.get("leverage") or 1))
                )
            margins[pos["symbol"]] = max(margins.get(pos["symbol"], 0), position_margin)
        if contract.symbol in by_symbol:
            return None, "position_or_order_exists"
        if len(by_symbol) >= config.max_positions:
            return None, "position_limit"
        reserved = sum(by_symbol.values())
        equity, start = float(account["equity"]), float(account["day_start"])
        daily_free = start * config.day_loss_fraction - max(0, start - equity) - reserved
        portfolio_free = equity * config.portfolio_risk_fraction - reserved
        budget = min(equity * config.risk_fraction * fraction, daily_free, portfolio_free)
        if budget <= 0:
            return None, "risk_budget_exhausted"
        margin_free = equity * config.margin_fraction - sum(margins.values())
        if margin_free <= 0:
            return None, "margin_budget_exhausted"
        qty = floor_step(
            min(
                budget / unit_loss,
                margin_free * leverage / entry,
                depth * config.participation,
                instrument.max_qty,
            ),
            instrument.step,
        )
        if qty < instrument.minimum or qty * entry < instrument.min_notional:
            return None, "below_venue_minimum"
        risk = qty * unit_loss
        if risk > budget + 1e-9:
            return None, "rounded_risk_exceeded"
        payload = {
            "symbol": contract.symbol,
            "side": "Buy" if side == 1 else "Sell",
            "qty": format(Decimal(str(qty)), "f"),
            "price": format(Decimal(str(entry)), "f"),
            "stop": format(Decimal(str(stop)), "f"),
            "target": str(contract.target),
            "leverage": str(leverage),
            "orderLinkId": ident,
            "contract_id": contract.id,
            "model_version": contract.model_version,
            "policy_version": contract.config_version,
            "risk": risk,
            "budget": budget,
            "unit_loss": unit_loss,
            "expires": min(contract.expires, at + config.entry_ttl_s),
        }
        db.execute(
            "INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                mode,
                contract.symbol,
                contract.id,
                "pending",
                at,
                at,
                payload["expires"],
                risk,
                encode(payload),
                None,
                None,
            ),
        )
        return payload, "reserved"

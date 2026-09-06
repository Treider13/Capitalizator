"""Immutable reaction promises. Confirmation never reuses the origin event."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from capitalizator.fusion.atlas import Forecast
from capitalizator.fusion.config import Config
from capitalizator.fusion.market import Block
from capitalizator.fusion.store import encode


@dataclass(frozen=True)
class Contract:
    id: str
    symbol: str
    side: int
    created: float
    origin_block: int
    check_block: int
    end_block: int
    expires: float
    model_version: str
    config_version: str
    entry: float
    invalidation: float
    target: float
    expected_flow: float
    expected_refill: float
    remaining_edge: float
    origin_features: tuple[float, ...]
    definition: dict[str, Any]

    def evaluate(self, block: Block) -> tuple[str, str]:
        if block.at <= self.created or block.id <= self.origin_block:
            return "observing", "no_new_evidence"
        if (self.side == 1 and block.low <= self.invalidation) or (
            self.side == -1 and block.high >= self.invalidation
        ):
            return "refuted", "invalidation_traded"
        if block.at >= self.expires or block.id > self.end_block:
            return "expired", "reaction_deadline"
        if block.id < self.check_block:
            return "observing", "waiting_fixed_checkpoint"
        if block.id > self.check_block:
            return "expired", "checkpoint_missing"
        flow_ok = self.side * block.flow >= self.expected_flow
        refill_ok = self.side * block.refill >= self.expected_refill
        retained = self.side * (block.close - self.entry) >= 0
        if flow_ok and refill_ok and retained:
            return "confirmed", "new_flow_and_liquidity_reaction"
        return "refuted", "fixed_checkpoint_failed"

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def restore(cls, body: dict[str, Any]) -> Contract:
        body = dict(body)
        body["origin_features"] = tuple(body["origin_features"])
        return cls(**body)


def propose(
    symbol: str, block: Block, forecast: Forecast, config: Config, costs: float, tick: float
) -> tuple[Contract | None, str]:
    c = block.context
    side = int(c["sweep"])
    if side == 0:
        return None, "sweep_required"
    # Premium/discount retracement 0.5–1; OTE remains recorded, not counted as evidence.
    location = float(c["discount"])
    if not (0 <= location <= 0.5 if side == 1 else 0.5 <= location <= 1):
        return None, "outside_retracement"
    edge = forecast.edge(side, costs)
    if edge <= 0:
        return None, "no_robust_net_edge"
    tail = abs(forecast.lower if side == 1 else forecast.upper)
    buffer = max(tick, block.close * math.expm1(min(tail, 1.0)), float(c["ask"]) - float(c["bid"]))
    invalidation = float(c["sweep_extreme"]) - side * buffer
    target = float(c["resistance"] if side == 1 else c["support"])
    distance = side * (block.close - invalidation)
    reward = side * (target - block.close)
    if invalidation <= 0 or distance <= 0 or reward < config.minimum_rr * distance:
        return None, "insufficient_structural_reward"
    scenarios = np.asarray(forecast.scenarios)
    flow = max(0.0, float(np.quantile(side * scenarios[:, 1], config.confidence_alpha)))
    refill = float(np.quantile(side * scenarios[:, 2], config.confidence_alpha))
    definition = {
        "hypothesis": "sweep_reclaim_amplification",
        "alternative": "continued_pressure_or_absorption_failure",
        "support": c["support"],
        "resistance": c["resistance"],
        "evidence": ["future_signed_flow", "future_replenishment", "price_retention"],
        "checkpoint_policy": "one_fixed_checkpoint",
        "source_at": block.at,
        "costs": costs,
        "live_ready": forecast.live_ready,
    }
    ident = hashlib.sha256(
        encode([symbol, block.at, block.id, forecast.version, config.version]).encode()
    ).hexdigest()[:24]
    return Contract(
        ident,
        symbol,
        side,
        block.at,
        block.id,
        block.id + config.confirmation_blocks,
        block.id + config.horizon_blocks,
        block.at + config.contract_timeout_s,
        forecast.version,
        config.version,
        block.close,
        invalidation,
        target,
        flow,
        refill,
        edge,
        block.x,
        definition,
    ), "candidate"


def baseline(symbol: str, block: Block, config: Config, tick: float) -> Contract | None:
    """Explicit sweep/zone reference policy for ablation, without invented probabilities."""
    c, side = block.context, int(block.context["sweep"])
    if not side:
        return None
    stop = float(c["sweep_extreme"]) - side * max(tick, block.x[3] * block.close)
    target = float(c["resistance"] if side == 1 else c["support"])
    if side * (target - block.close) < config.minimum_rr * abs(block.close - stop):
        return None
    ident = hashlib.sha256(encode(["baseline", symbol, block.id, block.at]).encode()).hexdigest()[
        :24
    ]
    return Contract(
        ident,
        symbol,
        side,
        block.at,
        block.id,
        block.id + config.confirmation_blocks,
        block.id + config.horizon_blocks,
        block.at + config.contract_timeout_s,
        "rule_baseline",
        config.version,
        block.close,
        stop,
        target,
        0.0,
        0.0,
        0.0,
        block.x,
        {"hypothesis": "zone_sweep_reversal", "probability": None},
    )

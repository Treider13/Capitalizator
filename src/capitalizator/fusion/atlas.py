"""Conditional response ensemble, joint empirical scenarios and purged validation.

Three observed-flow regimes are fitted by soft responsibilities. They describe
aggregate responses, not identifiable wallets. Every output retains uncertainty.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from capitalizator.fusion.config import Config
from capitalizator.fusion.store import encode


def responsibilities(z: np.ndarray) -> np.ndarray:
    # Trend-following, absorption, neutral are hypotheses about observed responses.
    strength = z[:, 0] * z[:, 1]
    logits = np.stack((strength, -strength, -np.abs(strength)), axis=1)
    logits = np.clip(logits, -20, 20)
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    return np.asarray(exp / exp.sum(axis=1, keepdims=True))


@dataclass(frozen=True)
class Forecast:
    version: str
    means: tuple[tuple[float, ...], ...]
    scenarios: tuple[tuple[float, ...], ...]
    lower: float
    upper: float
    disagreement: float
    live_ready: bool

    def edge(self, side: int, costs: float) -> float:
        # Worst conditional model mean, with estimation uncertainty. Outcome tails
        # remain separate: requiring every individual trade to win is not the goal.
        values = [side * row[0] for row in self.means]
        return min(values) - self.disagreement - costs


@dataclass(frozen=True)
class Atlas:
    version: str
    body: dict[str, Any]
    report: dict[str, Any]

    def predict(self, x: tuple[float, ...] | list[float], alpha: float) -> Forecast:
        mean = np.asarray(self.body["mean"])
        scale = np.asarray(self.body["scale"])
        z = np.clip((np.asarray(x) - mean) / scale, -20, 20)
        vector = np.r_[1.0, z]
        predictions = np.asarray([vector @ np.asarray(c) for c in self.body["coefficients"]])
        residuals = np.asarray(self.body["residuals"])
        weights = responsibilities(z[None, :])[0]
        point = weights @ predictions
        scenarios = residuals + point
        # Calibrated residual RMS / effective calibration count is an estimation
        # error approximation, not a promise of conditional coverage.
        error = float(self.body["mean_error"])
        return Forecast(
            self.version,
            tuple(tuple(float(v) for v in r) for r in predictions),
            tuple(tuple(float(v) for v in r) for r in scenarios),
            float(np.quantile(scenarios[:, 0], alpha)),
            float(np.quantile(scenarios[:, 0], 1 - alpha)),
            error,
            bool(self.report.get("passed")),
        )


def _fit(x: np.ndarray, y: np.ndarray, ridge: float) -> tuple[Any, Any, Any]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-10] = 1.0
    z = np.clip((x - mean) / scale, -20, 20)
    design = np.column_stack((np.ones(len(x)), z))
    weights = responsibilities(z)
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 1e-10
    coefs = []
    for k in range(3):
        weighted = design * np.sqrt(weights[:, k, None])
        target = y * np.sqrt(weights[:, k, None])
        coefs.append(np.linalg.solve(weighted.T @ weighted + penalty, weighted.T @ target))
    return mean, scale, np.asarray(coefs)


def _predict(x: np.ndarray, mean: Any, scale: Any, coefficients: Any) -> np.ndarray:
    z = np.clip((x - mean) / scale, -20, 20)
    design = np.column_stack((np.ones(len(x)), z))
    predictions = np.stack([design @ c for c in coefficients], axis=1)
    return np.asarray(np.einsum("nk,nkt->nt", responsibilities(z), predictions))


def train(rows: list[dict[str, Any]], config: Config, at: float) -> Atlas | None:
    rows = sorted((r for r in rows if r["available"] <= at), key=lambda r: r["origin"])
    if len(rows) < config.demo_samples:
        return None
    n = len(rows)
    boundary1, boundary2 = rows[int(n * 0.6)]["origin"], rows[int(n * 0.8)]["origin"]
    fit_rows = [r for r in rows if r["available"] < boundary1]
    calibration = [r for r in rows if boundary1 <= r["origin"] and r["available"] < boundary2]
    test = [r for r in rows if r["origin"] >= boundary2]
    if min(len(fit_rows), len(calibration), len(test)) < 8:
        return None
    x, y = np.asarray([r["x"] for r in fit_rows]), np.asarray([r["y"] for r in fit_rows])
    cx, cy = np.asarray([r["x"] for r in calibration]), np.asarray([r["y"] for r in calibration])
    choices = []
    # Regularization grid, selected only on calibration; untouched chronological test follows.
    for ridge in (0.1, 1.0, 10.0, 100.0):
        mean, scale, coefs = _fit(x, y, ridge)
        pred = _predict(cx, mean, scale, coefs)
        loss = float(np.mean((pred[:, 0] - cy[:, 0]) ** 2))
        choices.append((loss, ridge, mean, scale, coefs, pred))
    _, ridge, mean, scale, coefs, cp = min(choices, key=lambda r: r[0])
    residuals = cy - cp
    tx, ty = np.asarray([r["x"] for r in test]), np.asarray([r["y"] for r in test])
    tp = _predict(tx, mean, scale, coefs)
    tz = np.clip((tx - mean) / scale, -20, 20)
    experts = np.stack([np.column_stack((np.ones(len(tx)), tz)) @ c for c in coefs], axis=1)
    error = float(
        np.std(residuals[:, 0], ddof=1) / np.sqrt(max(1, len(calibration) / config.horizon_blocks))
    )
    # Approximate time buckets keep simultaneous symbols together; they are not independent.
    horizon = max(float(np.median([r["available"] - r["origin"] for r in test])), 0.001)
    net: list[float] = []
    baseline: list[float] = []
    by_cluster: dict[int, list[float]] = {}
    directions: list[int] = []
    thresholds: list[float] = []
    for row, prediction, actual in zip(test, experts, ty, strict=True):
        costs = float(row["context"].get("costs", 0.0012))
        # Validate the same worst-expert/estimation-error veto used by Forecast.edge.
        # The mixture mean alone used to count trades the runtime would never admit.
        buy_edge = float(prediction[:, 0].min()) - error - costs
        sell_edge = float((-prediction[:, 0]).min()) - error - costs
        direction = 1 if buy_edge > 0 else -1 if sell_edge > 0 else 0
        directions.append(direction)
        thresholds.append(costs)
        result = direction * float(actual[0]) - abs(direction) * costs
        net.append(result)
        baseline.append(float(actual[0]) - costs)
        cluster = int(row["origin"] / horizon)
        by_cluster.setdefault(cluster, []).append(result)
    clusters = np.asarray([np.mean(v) for v in by_cluster.values()])
    rng = np.random.default_rng(0)
    # Time buckets can still be dependent; resample neighbouring buckets together.
    width = max(2, int(np.sqrt(len(clusters))))
    starts = rng.integers(0, len(clusters), (1000, int(np.ceil(len(clusters) / width))))
    indices = (starts[:, :, None] + np.arange(width)) % len(clusters)
    boot = np.mean(clusters[indices.reshape(1000, -1)[:, : len(clusters)]], axis=1)
    lower = float(np.quantile(boot, config.confidence_alpha))
    mse = float(np.mean((tp[:, 0] - ty[:, 0]) ** 2))
    zero_mse = float(np.mean(ty[:, 0] ** 2))
    mean_net = float(np.mean(net))
    reasons = []
    if n < config.live_samples:
        reasons.append("insufficient_samples")
    if len(clusters) < 32:
        reasons.append("insufficient_time_clusters")
    if not any(directions):
        reasons.append("no_cost_covering_signals")
    if lower <= 0:
        reasons.append("nonpositive_lower_net")
    if mse >= zero_mse:
        reasons.append("no_improvement_over_zero")
    if mean_net <= max(0, float(np.mean(baseline))):
        reasons.append("no_net_advantage_over_baseline")
    report = {
        "train_n": len(fit_rows),
        "calibration_n": len(calibration),
        "test_n": len(test),
        "clusters": len(clusters),
        "ridge": ridge,
        "test_mse": mse,
        "zero_mse": zero_mse,
        "mean_net": mean_net,
        "lower_mean_net": lower,
        "buy_hold_mean": float(np.mean(baseline)),
        "through": max(r["available"] for r in rows),
        "passed": not reasons,
        "rejection_reasons": reasons,
        "signal_count": sum(d != 0 for d in directions),
        "buy_signals": directions.count(1),
        "sell_signals": directions.count(-1),
        "abstentions": directions.count(0),
        "median_cost_bps": float(np.median(thresholds)) * 10000,
        "median_abs_prediction_bps": float(np.median(np.abs(tp[:, 0]))) * 10000,
        "mean_error_bps": error * 10000,
        "sample_span_s": max(r["available"] for r in rows) - min(r["origin"] for r in rows),
        "median_label_horizon_s": horizon,
        "bootstrap_block_clusters": width,
        "scope": "purged model test; execution and full-strategy validation are separate",
    }
    # Bounded deterministic residual reservoir; preserve joint target dependence.
    indices = np.linspace(0, len(residuals) - 1, min(256, len(residuals)), dtype=int)
    body = {
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "coefficients": coefs.tolist(),
        "residuals": residuals[indices].tolist(),
        "mean_error": error,
        "config": config.version,
    }
    version = hashlib.sha256(encode({"body": body, "report": report}).encode()).hexdigest()[:24]
    return Atlas(version, body, report)

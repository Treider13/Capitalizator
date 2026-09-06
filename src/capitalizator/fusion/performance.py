"""Realized performance from unique fills; no paper P&L in the venue ledger."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from capitalizator.fusion.store import Store


def metrics(
    returns: list[float], periods: float = 365.0, *, compound: bool = False
) -> dict[str, Any]:
    a = np.asarray(returns, dtype=float)
    if not len(a):
        return {
            "n": 0,
            "win_rate": None,
            "profit_factor": None,
            "sharpe": None,
            "max_drawdown": None,
            "net": 0.0,
        }
    positive, negative = float(a[a > 0].sum()), float(-a[a < 0].sum())
    curve = np.r_[1.0, np.cumprod(1 + a)] if compound else np.r_[0.0, np.cumsum(a)]
    peaks = np.maximum.accumulate(curve)
    dd = (peaks - curve) / peaks if compound else peaks - curve
    sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    return {
        "n": len(a),
        "win_rate": float(np.mean(a > 0)),
        "profit_factor": positive / negative if negative else None,
        "sharpe": float(a.mean()) / sd * math.sqrt(periods) if sd else None,
        "max_drawdown": float(dd.max()),
        "net": float(curve[-1] - 1) if compound else float(a.sum()),
    }


def venue_performance(store: Store, mode: str) -> dict[str, Any]:
    with store.analytics_lock:
        revision = store.meta("execution_revision:" + mode, 0)
        cached = store.meta("performance:" + mode)
        if cached is not None and cached["revision"] == revision:
            return dict(cached["report"])
        report = _venue_performance(store, mode)
        store.put_meta("performance:" + mode, {"revision": revision, "report": report})
        return report


def _venue_performance(store: Store, mode: str) -> dict[str, Any]:
    rows = store.rows("SELECT * FROM executions WHERE mode=? ORDER BY at,id", (mode,))
    inventory: dict[str, tuple[float, float, float]] = {}
    episodes: list[float] = []
    fees = realized = 0.0
    incomplete = False
    for record in rows:
        row = json.loads(record["body"])
        fee = float(row.get("execFee") or 0)
        fees += fee
        if row.get("execType", "Trade") == "Funding":
            symbol = row["symbol"]
            if symbol in inventory:
                held, average, pnl = inventory[symbol]
                inventory[symbol] = (held, average, pnl - fee)
            continue
        if (
            not row.get("execPrice")
            or not row.get("execQty")
            or row.get("side") not in {"Buy", "Sell"}
        ):
            incomplete = True
            continue
        qty = float(row.get("execQty") or 0) * (1 if row["side"] == "Buy" else -1)
        price = float(row["execPrice"])
        symbol = row["symbol"]
        held, average, pnl = inventory.get(symbol, (0.0, 0.0, 0.0))
        if float(row.get("closedSize") or 0) > abs(held) + 1e-10:
            incomplete = True
        pnl -= fee
        if held * qty >= 0:
            new = held + qty
            average = (abs(held) * average + abs(qty) * price) / abs(new) if new else 0.0
        else:
            closing = min(abs(held), abs(qty))
            gain = closing * (price - average) * (1 if held > 0 else -1)
            realized += gain
            pnl += gain
            new = held + qty
            if abs(new) < 1e-10 or held * new < 0:
                episodes.append(pnl)
                pnl = 0.0
                average = price if new else 0.0
        inventory[symbol] = (new, average, pnl)
    lower = None
    if len(episodes) >= 32:
        # Circular moving-block bootstrap, preserving neighbouring trade dependence.
        # This is a diagnostic, not proof of stationarity or future profitability.
        values = np.asarray(episodes[-8192:])
        width = max(2, int(math.sqrt(len(values))))
        starts = np.random.default_rng(0).integers(
            0, len(values), (1000, math.ceil(len(values) / width))
        )
        indices = (starts[:, :, None] + np.arange(width)) % len(values)
        means = values[indices.reshape(1000, -1)[:, : len(values)]].mean(axis=1)
        lower = float(np.quantile(means, 0.1))
    return {
        "mode": mode,
        "executions": len(rows),
        "closed_episodes": len(episodes),
        "realized_gross": realized,
        "fees": fees,
        "realized_net": realized - fees,
        "episodes": metrics(episodes, periods=1),
        "lower_episode_net": lower,
        "incomplete_inventory": incomplete,
        "scope": "unique available executions; account equity includes unrealized P&L",
    }

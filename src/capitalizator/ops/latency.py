"""0.1.4 — p50/p95 of recv_ts - exchange_ts. Does not invent a live hour.

Decision path: p50/p95 of journal `decision_ms` (jury/close − touch.ts).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from capitalizator.types import MarketEvent


def lag_ms(event: MarketEvent) -> float:
    return (event.recv_ts - event.exchange_ts).total_seconds() * 1000


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile. p in (0, 100]."""
    if not sorted_values:
        raise ValueError("no values")
    if p <= 0 or p > 100:
        raise ValueError("percentile must be in (0, 100]")
    rank = math.ceil(p / 100 * len(sorted_values))
    return float(sorted_values[max(0, rank - 1)])


def lag_report(events: Sequence[MarketEvent]) -> dict[str, float]:
    lags = sorted(lag_ms(e) for e in events)
    if not lags:
        raise ValueError("no events")
    return {"n": float(len(lags)), "p50_ms": percentile(lags, 50), "p95_ms": percentile(lags, 95)}


def decision_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """p50/p95 of journalled decision_ms. Rows without the field are skipped."""
    values = sorted(float(row["decision_ms"]) for row in rows if row.get("decision_ms") is not None)
    if not values:
        raise ValueError("no decisions")
    return {
        "n": float(len(values)),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
    }

"""Offline first-barrier labels; future prices never enter the online observer."""

from __future__ import annotations

import json
import math
from collections import Counter, deque
from pathlib import Path
from typing import Any

from capitalizator.fusion.archive import events
from capitalizator.fusion.risk import Instrument
from capitalizator.fusion.store import Store


def label_episodes(
    source: Store,
    root: Path,
    observations: list[dict[str, Any]],
    instruments: dict[str, Instrument],
    *,
    max_age_s: float,
) -> dict[str, Any]:
    """Label first detection and each transition to recovery, including censored rows.

    Width is fixed using the already observed 120s price range, two ticks and
    round-trip taker fees. These are diagnostic price labels, not executable PnL.
    All instruments share UTC-day clusters; overlapping horizons aren't trials.
    """
    signals: list[dict[str, Any]] = []
    phases: dict[str, str] = {}
    for row in observations:
        state = json.loads(row["body"])
        if state["quality"] != "ready":
            continue
        for ep in state["episodes"]:
            previous = phases.get(ep["id"])
            phases[ep["id"]] = ep["state"]
            if previous is not None and not (ep["state"] == "recovery" and previous != "recovery"):
                continue
            window = state["metrics"]["windows"]["120"]
            price = float(window["last"])
            instrument = instruments[row["symbol"]]
            if price <= 0:
                continue
            width = max(
                float(window["high"]) - float(window["low"]),
                2 * instrument.tick,
                price * 2 * instrument.taker,
            )
            for horizon in (60, 300, 900):
                signals.append(
                    {
                        "episode": ep["id"],
                        "symbol": row["symbol"],
                        "direction": ep["direction"],
                        "phase": "detection" if previous is None else "recovery",
                        "at": row["at"],
                        "price": price,
                        "width": width,
                        "horizon_s": horizon,
                        "deadline": row["at"] + horizon,
                        "last_trade": row["at"],
                        "outcome": None,
                    }
                )
    signals.sort(key=lambda s: s["at"])
    active: list[dict[str, Any]] = []
    cursor = 0
    last_receipts: dict[str, float] = {}
    regressed_symbols: set[str] = set()
    trade_ids: set[tuple[str, str]] = set()
    id_queue: deque[tuple[str, str]] = deque()
    for event in events(source, root):
        at, symbol = event["received"], event["symbol"]
        if event["kind"] in {"book", "trades", "ticker", "liquidation", "gap"}:
            if not math.isfinite(at) or at < last_receipts.get(symbol, -math.inf):
                regressed_symbols.add(symbol)
            last_receipts[symbol] = at
        while cursor < len(signals) and signals[cursor]["at"] < at:
            active.append(signals[cursor])
            cursor += 1
        pending = [s for s in active if s["symbol"] == symbol and s["at"] < at]
        kind = event["kind"]
        if kind == "gap":
            for signal in pending:
                signal["outcome"] = "censored_data_gap"
        elif kind == "trades":
            # Validate the whole received packet before assigning any outcome.
            # A first barrier hit cannot conceal a corrupt later row.
            prices: list[float] = []
            invalid = False
            try:
                body = json.loads(event["body"])
                rows = body.get("data") if isinstance(body, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("trade data must be a list")
                for trade in rows:
                    if not isinstance(trade, dict):
                        raise ValueError("trade row must be an object")
                    ident = trade.get("i")
                    if ident is not None:
                        key = (symbol, str(ident))
                        if key in trade_ids:
                            continue
                        trade_ids.add(key)
                        id_queue.append(key)
                        if len(id_queue) > 100000:
                            trade_ids.remove(id_queue.popleft())
                    price, stamp = float(trade["p"]), float(trade["T"]) / 1000
                    if (
                        not math.isfinite(price + stamp)
                        or price <= 0
                        or not 0 <= at - stamp <= max_age_s
                    ):
                        raise ValueError("invalid price or exchange timestamp")
                    prices.append(price)
            except (KeyError, ValueError, TypeError, OverflowError):
                invalid = True
            if invalid:
                for signal in pending:
                    signal["outcome"] = "censored_invalid_trade"
                active = [s for s in active if s["outcome"] is None]
                continue
            if not prices:
                continue
            for signal in pending:
                if at < signal["last_trade"] or at - signal["last_trade"] > max_age_s:
                    signal["outcome"] = "censored_trade_gap"
                    continue
                if at > signal["deadline"]:
                    signal["outcome"] = "neither_barrier"
                    continue
                signal["last_trade"] = at
                for price in prices:
                    movement = (price - signal["price"]) * (
                        -1 if signal["direction"] == "sell" else 1
                    )
                    if abs(movement) >= signal["width"]:
                        signal["outcome"] = (
                            "continuation_first" if movement > 0 else "recovery_first"
                        )
                        signal["outcome_at"] = at
                        break
                if signal["outcome"] is None and at == signal["deadline"]:
                    signal["outcome"] = "neither_barrier"
        active = [s for s in active if s["outcome"] is None]
    for signal in signals:
        if signal["symbol"] in regressed_symbols:
            # Receipt-time signals cannot be aligned reliably to an unordered tape.
            signal["outcome"] = "censored_receipt_order"
            signal.pop("outcome_at", None)
        if signal["outcome"] is None:
            signal["outcome"] = "censored_end_of_recording"
        del signal["last_trade"]
    days = {int(s["at"] // 86400) for s in signals}
    return {
        "label_version": "receipt-barriers-2",
        "method": (
            "receipt-time first barrier; "
            "fixed predecision 120s range/2 ticks/round-trip fee maximum"
        ),
        "horizons_s": [60, 300, 900],
        "receipt_order_rejected_symbols": sorted(regressed_symbols),
        "distinct_episodes": len({s["episode"] for s in signals}),
        "utc_day_clusters": len(days),
        "outcomes": dict(Counter(s["outcome"] for s in signals)),
        "labels": signals,
        "limitations": [
            "price labels exclude spread, impact and funding; "
            "strategy replay accounts for execution costs",
            "same episode and overlapping BTC/ETH horizons are correlated, not independent trials",
            "confidence intervals and holdout validation require a predefined statistical analysis",
            "absence of a detected gap does not prove complete exchange feed coverage",
        ],
    }

"""Read-only expanding walk-forward audit of recorded Atlas samples, not a fill backtest."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from capitalizator.fusion.atlas import train
from capitalizator.fusion.config import Config


def audit(rows: list[dict[str, Any]], config: Config, folds: int = 3) -> dict[str, Any]:
    if not 1 <= folds <= 10:
        raise ValueError("folds must be between 1 and 10")
    rows = sorted(rows, key=lambda r: (r["origin"], r.get("id", "")))
    if len(rows) < max(config.demo_samples * 2, 128):
        raise ValueError("insufficient recorded samples for independent forward folds")
    cuts = np.linspace(int(len(rows) * 0.6), len(rows), folds + 1, dtype=int)
    reports = []
    for i, (left, right) in enumerate(zip(cuts[:-1], cuts[1:], strict=True)):
        start = rows[int(left)]["origin"]
        end = rows[int(right)]["origin"] if right < len(rows) else float("inf")
        fit = [r for r in rows if r["available"] < start]
        holdout = [r for r in rows if start <= r["origin"] < end]
        model = train(fit, config, start)
        if not holdout or model is None:
            reports.append({"fold": i + 1, "status": "insufficient_purged_history"})
            continue
        outcomes: list[float] = []
        signals = 0
        for r in holdout:
            forecast = model.predict(r["x"], config.confidence_alpha)
            cost = float(r["context"].get("costs", 0.0012))
            side = 1 if forecast.edge(1, cost) > 0 else -1 if forecast.edge(-1, cost) > 0 else 0
            signals += int(side != 0)
            outcomes.append(side * float(r["y"][0]) - abs(side) * cost)
        reports.append(
            {
                "fold": i + 1,
                "status": "evaluated",
                "model": model.version,
                "train_through": model.report["through"],
                "test_start": start,
                "test_end": max(r["available"] for r in holdout),
                "train_samples": len(fit),
                "test_samples": len(holdout),
                "signals": signals,
                "mean_net_label_proxy": float(np.mean(outcomes)),
                "training_report": model.report,
            }
        )
    return {
        "scope": "recorded label walk-forward proxy; not executed trades or strategy P&L",
        "samples": len(rows),
        "symbols": dict(Counter(r.get("symbol", "unknown") for r in rows)),
        "sample_start": rows[0]["origin"],
        "sample_end": max(r["available"] for r in rows),
        "folds": reports,
        "limitations": [
            "Excludes HTF/LTF, sweep, daily, news, reaction, fills and portfolio risk gates.",
            "Overlapping label returns cannot be summed into account returns.",
            "A positive proxy does not establish executable profitability.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--userdir", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--policy")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--max-rows", type=int, default=32768)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 128 <= args.max_rows <= 200000:
        parser.error("max-rows must be 128..200000")
    config_path = args.config or args.userdir / "config.json"
    config = Config.load(config_path if args.config or config_path.exists() else None)
    db = sqlite3.connect(
        (args.userdir / "fusion.sqlite3").resolve().as_uri() + "?mode=ro", uri=True, timeout=5
    )
    db.row_factory = sqlite3.Row
    try:
        epoch = db.execute("SELECT body FROM meta WHERE key='policy_epoch'").fetchone()
        policy = args.policy or (json.loads(epoch["body"])["version"] if epoch else config.version)
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM samples WHERE available<=? "
                "AND json_extract(context,'$.policy_version')=? "
                "ORDER BY available DESC,id DESC LIMIT ?",
                (time.time(), policy, args.max_rows),
            )
        ]
    finally:
        db.close()
    for r in rows:
        for key in ("x", "y", "context"):
            r[key] = json.loads(r[key])
    result = {
        "source_policy": policy,
        "evaluation_policy": config.version,
        **audit(rows, config, args.folds),
    }
    text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()

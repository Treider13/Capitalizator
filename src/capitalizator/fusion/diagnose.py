"""Compact read-only phone diagnostic: status plus a bounded decision journal sample."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from capitalizator.fusion.config import Config
from capitalizator.fusion.cross_market import entry_check
from capitalizator.fusion.diagnostics import redact, redact_fields


def decision_sample(path: Path, limit: int = 20000) -> dict[str, Any]:
    if not 1 <= limit <= 50000:
        raise ValueError("decision limit must be 1..50000")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    deadline = time.monotonic() + 2
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        # Bound rows before extracting JSON, and never materialize bulky pressure snapshots.
        rows = db.execute(
            "SELECT id,at,symbol,kind,CASE WHEN kind != 'pressure_observation' "
            "THEN json_extract(body,'$.reason') END AS reason FROM "
            "(SELECT * FROM decisions ORDER BY id DESC LIMIT ?)",
            (limit,),
        ).fetchall()
    finally:
        db.close()
    reasons: dict[str, Counter[str]] = {}
    for _, _, symbol, kind, reason in rows:
        if reason:
            reasons.setdefault(symbol, Counter())[f"{kind}:{reason}"] += 1
    return {
        "scope": "recent journal records; mixed stages, not probabilities or all trading history",
        "records": len(rows),
        "limit": limit,
        "first_at": min((r[1] for r in rows), default=None),
        "last_at": max((r[1] for r in rows), default=None),
        "reasons": {symbol: dict(counts.most_common()) for symbol, counts in reasons.items()},
    }


def summarize(status: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    cfg_data = dict(status.get("config") or {})
    if "symbols" in cfg_data:
        cfg_data["symbols"] = tuple(cfg_data["symbols"])
    cfg = Config(**cfg_data)
    at = float(status["at"])
    model = status.get("active_model_report") or {}
    pairs = {}
    for symbol in cfg.symbols:
        market = (status.get("markets") or {}).get(symbol, {})
        news = ((status.get("news") or {}).get("coverage") or {}).get(symbol, {})
        pairs[symbol] = {
            "spot_required": cfg.requires_spot(symbol),
            "book_checks": {
                side: entry_check(
                    market.get("cross_market") or {},
                    direction,
                    at,
                    cfg,
                    symbol=symbol,
                    monotonic_at=status.get("monotonic_at"),
                )
                for side, direction in (("Buy", 1), ("Sell", -1))
            },
            "news_ok": bool(news.get("ok") and 0 <= at - news.get("at", 0) <= cfg.news_stale_s),
            "news_missing": news.get("missing"),
            "top_recorded_reasons": list((history.get("reasons", {}).get(symbol) or {}).items())[
                :3
            ],
        }
    return {
        "at": at,
        "uptime_s": status.get("uptime_s"),
        "mode": status.get("mode"),
        "paused": status.get("paused"),
        "pause_state": status.get("pause_state"),
        "halted": status.get("halted"),
        "halt_reason": status.get("reason"),
        "broker": status.get("broker"),
        "worker_errors": status.get("worker_errors"),
        "last_failure": status.get("last_failure"),
        "run_id": status.get("run_id"),
        "model": status.get("model"),
        "model_report": model,
        "pairs": pairs,
        "history": history,
        "scope": "book checks and recorded reasons; ready books alone do not authorize an entry",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--userdir", type=Path, required=True)
    p.add_argument("--port", type=int)
    p.add_argument("--json", action="store_true")
    p.add_argument("--pair")
    args = p.parse_args()
    config_path = args.userdir / "config.json"
    cfg = Config.load(config_path if config_path.exists() else None)
    port = args.port or cfg.api_port
    with urlopen(f"http://127.0.0.1:{port}/api/status", timeout=10) as response:
        status = json.load(response)
    try:
        history = decision_sample(args.userdir / "fusion.sqlite3")
    except (sqlite3.Error, OSError) as exc:
        history = {"error": redact(str(exc))}
    report = summarize(status, history)
    if args.pair:
        if args.pair not in report["pairs"]:
            p.error("pair is not configured")
        report["pairs"] = {args.pair: report["pairs"][args.pair]}
    if args.json:
        print(json.dumps(redact_fields(report), ensure_ascii=False, indent=2, allow_nan=False))
        return
    m = report["model_report"]
    print(f"mode={report['mode']} uptime={report['uptime_s']} paused={report['paused']}")
    print(redact(f"halt={report['halt_reason']} broker={report['broker']}"))
    print(
        f"model_passed={m.get('passed')} signals={m.get('signal_count')} "
        f"reject={m.get('rejection_reasons')}"
    )
    failure = report["last_failure"] or {}
    print(redact(f"failure={failure.get('worker')} {failure.get('error', '')}"))
    for symbol, pair in report["pairs"].items():
        print(
            f"{symbol} book={pair['book_checks']['Buy']}/{pair['book_checks']['Sell']} "
            f"news={pair['news_ok']} missing={pair['news_missing']}"
        )
        if pair["top_recorded_reasons"]:
            print(
                "  reasons="
                + "; ".join(f"{name}({count})" for name, count in pair["top_recorded_reasons"])
            )
    print(f"history_records={history.get('records')} error={history.get('error')}")


if __name__ == "__main__":
    main()

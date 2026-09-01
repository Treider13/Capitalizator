"""Phase gates. Exit 0 pass, 2 fail (phase continues), 3 accident.

F0 stays red until 30d tape, kill-switch log, checked withdraw, and CI gitleaks exist.
This process does not flip infra/phase.yaml.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, get_args

import yaml

from capitalizator.ops.phase import breakout_enabled, equity_source
from capitalizator.ops.phase import trading_mode as read_trading_mode
from capitalizator.ops.thresholds import load_gates
from capitalizator.risk.schema import FORBIDDEN_ACTIONS, RiskAction

PASS = 0
FAIL = 2
ACCIDENT = 3


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "infra" / "phase.yaml").is_file():
            return parent
    raise FileNotFoundError("infra/phase.yaml not found")


def gate_f0(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    base = root or repo_root()
    prs = base / "src" / "capitalizator" / "prs"
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(prs.glob("*.py")))
    checklist = (base / "ops" / "key-checklist.md").read_text(encoding="utf-8")
    withdraw = next((ln for ln in checklist.splitlines() if "Withdraw" in ln), "")
    checks: dict[str, bool] = {
        "G0.5_no_place_order": "place_order" not in text and "create_order" not in text,
        "G0.1_uptime_30d": (base / "ops" / "uptime-30d.md").is_file(),
        "G0.6_kill_switch": (base / "ops" / "kill-switch-week4.md").is_file(),
        "G0.7_withdraw_checked": "[x]" in withdraw.lower(),
        "G0.9_gitleaks_ci": False,
        "trading_mode_off": read_trading_mode() == "off",
    }
    accident = "average_in" in text
    passed = all(checks.values())
    code = ACCIDENT if accident else (PASS if passed else FAIL)
    return code, {"gate": "f0", "ok": passed, "checks": checks, "exit": code}


def _f1_closed_bounce(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    try:
        fill_qty = float(row.get("fill_qty") or 0)
        r = row.get("r")
        float(r)
    except (TypeError, ValueError):
        return False
    return (
        row.get("mode") == "demo"
        and row.get("setup_tag") == "bounce"
        and row.get("status") == "closed"
        and fill_qty > 0
        and r is not None
    )


def _episode_rows(path: Path) -> list[object]:
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("episodes") or []
    return list(rows) if isinstance(rows, list) else []


def gate_f1(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    """F1 stays red until ≥80 closed demo bounces exist. We do not invent them."""
    base = root or repo_root()
    zlg = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((base / "src" / "capitalizator" / "zlg").glob("*.py"))
    )
    rows = _episode_rows(base / "ops" / "gates" / "f1_episodes.json")
    closed = [row for row in rows if _f1_closed_bounce(row)]
    n_bounce = len(closed)
    rs = [float(row["r"]) for row in closed if isinstance(row, dict)]
    avg_r = (sum(rs) / len(rs)) if rs else None
    n_breakout = sum(
        1 for row in rows if isinstance(row, dict) and row.get("setup_tag") == "breakout"
    )
    checks: dict[str, bool] = {
        "G1.1_n80": n_bounce >= 80,
        "G1.2_avg_r_pos": avg_r is not None and avg_r > 0,
        "G1.3_no_average": "average_in" in FORBIDDEN_ACTIONS
        and "average_in" not in get_args(RiskAction),
        "G1.4_zlg_no_random": "random" not in zlg,
        "G1.5_breakout_off": (not breakout_enabled()) and n_breakout == 0,
    }
    accident = "average_in" not in FORBIDDEN_ACTIONS
    passed = all(checks.values())
    code = ACCIDENT if accident else (PASS if passed else FAIL)
    return code, {
        "gate": "f1",
        "ok": passed,
        "checks": checks,
        "n_bounce": n_bounce,
        "n_breakout": n_breakout,
        "avg_r": avg_r,
        "exit": code,
    }


_LLM_VERIFIED_ASSIGN = (
    'verdict = "VERIFIED"',
    "verdict='VERIFIED'",
    '.verdict = "VERIFIED"',
)


def _llm_assigns_verified(base: Path) -> bool:
    llm = base / "src" / "capitalizator" / "llm"
    if not llm.is_dir():
        return False
    for path in sorted(llm.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in _LLM_VERIFIED_ASSIGN):
            return True
    return False


def gate_f2(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    """F2 stays red. Empty journals are unknown, not a clean pass."""
    base = root or repo_root()
    bounce = (base / "src" / "capitalizator" / "exec" / "strategy_bounce.py").read_text(
        encoding="utf-8"
    )
    cards = _episode_rows(base / "ops" / "gates" / "f2_cards.json")
    n_cards = sum(
        1
        for row in cards
        if isinstance(row, dict) and row.get("outcome_at") not in (None, "")
    )
    episodes = _episode_rows(base / "ops" / "gates" / "f1_episodes.json")
    closed = [row for row in episodes if _f1_closed_bounce(row)]
    n_against = sum(
        1
        for row in closed
        if isinstance(row, dict) and row.get("veto_btc_would_reject") is True
    )
    saved = _episode_rows(base / "ops" / "gates" / "f2_saved_r.json")
    n_veto = sum(
        1
        for row in saved
        if isinstance(row, dict) and row.get("reason") in {"btc_veto", "btc_break", "VETO"}
    )
    n_file = base / "ops" / "gates" / "f2_veto_n_insufficient.md"
    n_text = n_file.read_text(encoding="utf-8") if n_file.is_file() else ""
    n_insufficient = "n < 10" in n_text or "n<10" in n_text
    parsed_file = base / "ops" / "authors" / "parsed.jsonl"
    parsed_n = 0
    if parsed_file.is_file():
        from capitalizator.authors.parse import AuthorParse

        parsed_n = len(AuthorParse().from_jsonl(parsed_file))
    checks: dict[str, bool] = {
        "G2.1_veto_lived": n_veto >= 1,
        "G2.2_veto_shadow_or_n": n_insufficient,
        "G2.3_against_btc": len(closed) > 0 and n_against == 0,
        "G2.4_cards_50": n_cards >= 50,
        "G2.5_verifier_not_llm": not _llm_assigns_verified(base),
        "G2.6_redteam_ci": False,
        "G2_breakout_off": not breakout_enabled(),
        "G2_parsed_50": parsed_n >= 50,
        "G2_veto_in_propose": "BtcVeto" in bounce and "btc_veto.allow" in bounce,
    }
    # Veto is wired. The gate still fails on n_cards / lived veto journal.
    passed = all(
        checks[k]
        for k in (
            "G2.1_veto_lived",
            "G2.2_veto_shadow_or_n",
            "G2.3_against_btc",
            "G2.4_cards_50",
            "G2.5_verifier_not_llm",
            "G2.6_redteam_ci",
        )
    )
    code = FAIL if not passed else PASS
    return code, {
        "gate": "f2",
        "ok": passed,
        "checks": checks,
        "n_cards": n_cards,
        "n_veto": n_veto,
        "n_closed": len(closed),
        "n_against": n_against,
        "parsed_n": parsed_n,
        "exit": code,
    }


def _closed_demo(row: Any, tags: frozenset[str]) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("setup_tag") not in tags:
        return False
    try:
        fill_qty = float(row.get("fill_qty") or 0)
        r = row.get("r")
        float(r)
    except (TypeError, ValueError):
        return False
    return (
        row.get("mode") == "demo"
        and row.get("status") == "closed"
        and fill_qty > 0
        and r is not None
    )


def _closed_micro(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    try:
        fill_qty = float(row.get("fill_qty") or 0)
        r = row.get("r")
        float(r)
    except (TypeError, ValueError):
        return False
    return (
        row.get("mode") == "micro"
        and row.get("status") == "closed"
        and fill_qty > 0
        and r is not None
    )


def _avg_r(rows: list[Any]) -> float | None:
    rs = [float(row["r"]) for row in rows if isinstance(row, dict)]
    if not rs:
        return None
    return sum(rs) / len(rs)


def _weeks_spanned(rows: list[Any]) -> int | None:
    """DuckDB date_diff('week', min, max) + 1. No opened_at → unknown, not 8."""
    stamps: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("opened_at")
        if not raw:
            continue
        text = str(raw)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        stamps.append(parsed)
    if not stamps:
        return None
    days = (max(stamps) - min(stamps)).days
    return days // 7 + 1


def _whale_fills(episodes: list[object], cards: list[object]) -> int:
    reasons = {
        row.get("card_id"): row.get("entry_reason")
        for row in cards
        if isinstance(row, dict) and row.get("card_id")
    }
    n = 0
    for row in episodes:
        if not isinstance(row, dict):
            continue
        try:
            fill_qty = float(row.get("fill_qty") or 0)
        except (TypeError, ValueError):
            continue
        if fill_qty <= 0:
            continue
        reason = row.get("entry_reason") or reasons.get(row.get("card_id"))
        if reason == "whale":
            n += 1
    return n


def _f1_end_avg(base: Path) -> float | None:
    path = base / "ops" / "gates" / "f1_avg_r_at_end.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("avg_r")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def gate_f3(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    """F3 stays red. Empty journals are unknown, not 40 breakouts."""
    base = root or repo_root()
    th = load_gates(root=base)
    f3 = th["f3"]
    bounce_src = (base / "src" / "capitalizator" / "exec" / "strategy_bounce.py").read_text(
        encoding="utf-8"
    )
    episodes = _episode_rows(base / "ops" / "gates" / "f1_episodes.json")
    bounce = [row for row in episodes if _closed_demo(row, frozenset({"bounce"}))]
    brk = [row for row in episodes if _closed_demo(row, frozenset({"breakout"}))]
    combo = [row for row in episodes if _closed_demo(row, frozenset({"bounce", "breakout"}))]
    cards = _episode_rows(base / "ops" / "gates" / "f2_cards.json")
    n_break = len(brk)
    n_bounce = len(bounce)
    n_sum = len(combo)
    avg_sum = _avg_r(combo)
    avg_bounce = _avg_r(bounce)
    f1_end = _f1_end_avg(base)
    slack = float(f3["bounce_slack_r"])
    degraded_ok = (
        avg_bounce is not None
        and f1_end is not None
        and avg_bounce >= f1_end - slack
    )
    whale_n = _whale_fills(episodes, cards)
    squeeze_file = base / "ops" / "gates" / "f3_squeeze.json"
    checks: dict[str, bool] = {
        "G3.1_n40_break": n_break >= int(f3["n_break_demo_min"]),
        "G3.2_bounce_not_degraded": degraded_ok,
        "G3.3_n100_sum": n_sum >= int(f3["n_sum_demo_min"]),
        "G3.4_avg_r_pos": avg_sum is not None and avg_sum > float(f3["avg_r_sum_min"]),
        "G3.5_ai_quarantine": not _llm_assigns_verified(base),
        "G3.6_no_whale_entry": whale_n <= int(f3["whale_entries_max"]),
        "G3.7_squeeze": False,
        "G3_breakout_off": not breakout_enabled(),
        "G3_no_strategy_breakout": not (
            base / "src" / "capitalizator" / "exec" / "strategy_breakout.py"
        ).is_file(),
        "G3_failed_break_out": f3["failed_break_in_counts"] is False,
        "G3_whales_not_in_propose": "capitalizator.whales" not in bounce_src,
    }
    passed = all(
        checks[k]
        for k in (
            "G3.1_n40_break",
            "G3.2_bounce_not_degraded",
            "G3.3_n100_sum",
            "G3.4_avg_r_pos",
            "G3.5_ai_quarantine",
            "G3.6_no_whale_entry",
            "G3.7_squeeze",
        )
    )
    # G3.5 is True today (LLM does not stamp VERIFIED). Empty n is still fail.
    # G3.6 is True on an empty book (0 whale fills). That must not pass the gate.
    # G3.7 stays false until a pre-registered squeeze table exists. Empty ≠ in-band.
    code = FAIL if not passed else PASS
    return code, {
        "gate": "f3",
        "ok": passed,
        "checks": checks,
        "n_break": n_break,
        "n_bounce": n_bounce,
        "n_sum": n_sum,
        "avg_r_sum": avg_sum,
        "avg_r_bounce": avg_bounce,
        "f1_end_avg": f1_end,
        "whale_entries": whale_n,
        "squeeze_file": squeeze_file.is_file(),
        "exit": code,
    }


def gate_f4(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    """F4 stays red. Empty micro is wait, not 100 live AND 8 weeks."""
    base = root or repo_root()
    th = load_gates(root=base)
    f4 = th["f4"]
    rows = [
        row
        for row in _episode_rows(base / "ops" / "gates" / "f4_episodes.json")
        if _closed_micro(row)
    ]
    n_live = len(rows)
    weeks = _weeks_spanned(rows)
    rs = [float(row["r"]) for row in rows if isinstance(row, dict)]
    wr = (sum(1 for r in rs if r > 0) / len(rs)) if rs else None
    liq = sum(
        1
        for row in rows
        if isinstance(row, dict) and row.get("liquidated") is True
    )
    n_against = sum(
        1
        for row in rows
        if isinstance(row, dict) and row.get("veto_btc_would_reject") is True
    )
    overlay = _episode_rows(base / "ops" / "gates" / "f4_overlay.json")
    matched = sum(
        1
        for row in overlay
        if isinstance(row, dict)
        and row.get("r_live") is not None
        and row.get("r_shadow") is not None
    )
    n_min = int(f4["n_live_min"])
    w_min = int(f4["weeks_min"])
    checks: dict[str, bool] = {
        "G4.1_n100": n_live >= n_min,
        "G4.2_weeks8": weeks is not None and weeks >= w_min,
        "G4.3_and_not_or": True,
        "G4.4_wr": wr is not None and wr >= float(f4["wr_soft"]),
        "G4.5_overlay": matched >= int(f4["overlay"]["min_matched"]),
        "G4.6_liq0": len(rows) > 0 and liq <= int(f4["liq_max"]),
        "G4.7_against_btc": len(rows) > 0 and n_against == 0,
        "G4.8_no_average": "average_in" in FORBIDDEN_ACTIONS,
        "G4_trading_not_live": read_trading_mode() != "live",
        "G4_equity_not_main": equity_source() != "main",
    }
    gate_time = checks["G4.1_n100"] and checks["G4.2_weeks8"]
    passed = gate_time and all(
        checks[k]
        for k in (
            "G4.4_wr",
            "G4.5_overlay",
            "G4.6_liq0",
            "G4.7_against_btc",
            "G4.8_no_average",
        )
    )
    code = FAIL if not passed else PASS
    return code, {
        "gate": "f4",
        "ok": passed,
        "checks": checks,
        "n_live": n_live,
        "weeks_spanned": weeks,
        "wr": wr,
        "liq": liq,
        "n_against": n_against,
        "overlay_matched": matched,
        "gate_time": gate_time,
        "exit": code,
    }


def gate_f5kill(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    """F5 kill. Does not invent a −3% day. Does not write phase.yaml."""
    base = root or repo_root()
    th = load_gates(root=base)
    cap = float(th["f5"]["target_risk_max_until_written_otherwise"])
    raw = yaml.safe_load((base / "infra" / "phase.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("phase.yaml must be a mapping")
    target = float(raw.get("target_risk") or 0)
    over = target > cap + 1e-9
    ack = (base / "ops" / "gates" / "ack_f5.txt").is_file()
    in_f5 = equity_source() == "main" and ack
    pnl = base / "ops" / "gates" / "f5_pnl.json"
    checks: dict[str, bool] = {
        "K5_target_cap": not over,
        "K5_in_f5": in_f5,
        "K5_pnl_known": pnl.is_file(),
        "K5_no_average": "average_in" in FORBIDDEN_ACTIONS,
    }
    if over:
        code = ACCIDENT
    else:
        code = FAIL
    return code, {
        "gate": "f5kill",
        "ok": False,
        "checks": checks,
        "target_risk": target,
        "cap": cap,
        "ack": ack,
        "exit": code,
        "writes_phase": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", choices=("f0", "f1", "f2", "f3", "f4", "f5kill"))
    args = parser.parse_args(argv)
    runners = {
        "f0": gate_f0,
        "f1": gate_f1,
        "f2": gate_f2,
        "f3": gate_f3,
        "f4": gate_f4,
        "f5kill": gate_f5kill,
    }
    code, payload = runners[args.gate]()
    out = repo_root() / "ops" / "gates"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"last_{args.gate}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

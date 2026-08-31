"""Phase gates. Exit 0 pass, 2 fail (phase continues), 3 accident.

F0 stays red until 30d tape, kill-switch log, checked withdraw, and CI gitleaks exist.
This process does not flip infra/phase.yaml.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args

from capitalizator.ops.phase import breakout_enabled
from capitalizator.ops.phase import trading_mode as read_trading_mode
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
        "G2_veto_not_in_propose": (
            "from capitalizator.btc" not in bounce
            and "import BtcVeto" not in bounce
            and "BtcVeto()" not in bounce
        ),
    }
    # G2_veto_not_in_propose documents the hole: veto is paper, not live.
    # It is True today and must not make the gate pass.
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", choices=("f0", "f1", "f2"))
    args = parser.parse_args(argv)
    runners = {"f0": gate_f0, "f1": gate_f1, "f2": gate_f2}
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

"""Phase gates. Exit 0 pass, 2 fail (phase continues), 3 accident.

F0 stays red until 30d tape, kill-switch log, checked withdraw, and CI gitleaks exist.
This process does not flip infra/phase.yaml.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

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
    phase = (base / "infra" / "phase.yaml").read_text(encoding="utf-8")
    checks: dict[str, bool] = {
        "G0.5_no_place_order": "place_order" not in text and "create_order" not in text,
        "G0.1_uptime_30d": (base / "ops" / "uptime-30d.md").is_file(),
        "G0.6_kill_switch": (base / "ops" / "kill-switch-week4.md").is_file(),
        "G0.7_withdraw_checked": "[x]" in withdraw.lower(),
        "G0.9_gitleaks_ci": False,
        "trading_mode_off": "trading_mode: off" in phase,
    }
    accident = "average_in" in text
    passed = all(checks.values())
    code = ACCIDENT if accident else (PASS if passed else FAIL)
    return code, {"gate": "f0", "ok": passed, "checks": checks, "exit": code}


def gate_f1(*, root: Path | None = None) -> tuple[int, dict[str, object]]:
    """F1 stays red until ≥80 closed demo bounces exist. We do not invent them."""
    base = root or repo_root()
    phase = (base / "infra" / "phase.yaml").read_text(encoding="utf-8")
    schema = (base / "src" / "capitalizator" / "risk" / "schema.py").read_text(encoding="utf-8")
    zlg = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((base / "src" / "capitalizator" / "zlg").glob("*.py"))
    )
    episode_file = base / "ops" / "gates" / "f1_episodes.json"
    n_bounce = 0
    avg_r: float | None = None
    if episode_file.is_file():
        raw = json.loads(episode_file.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("episodes") or []
        n_bounce = len(rows)
        rs = [float(r["r"]) for r in rows if r.get("r") is not None]
        avg_r = (sum(rs) / len(rs)) if rs else None
    checks: dict[str, bool] = {
        "G1.1_n80": n_bounce >= 80,
        "G1.2_avg_r_pos": avg_r is not None and avg_r > 0,
        "G1.3_no_average": "average_in" in schema and "FORBIDDEN" in schema,
        "G1.4_zlg_no_random": "random" not in zlg,
        "G1.5_breakout_off": "breakout_enabled: false" in phase,
    }
    accident = n_bounce > 0 and "average_in" not in schema
    passed = all(checks.values())
    code = ACCIDENT if accident else (PASS if passed else FAIL)
    return code, {
        "gate": "f1",
        "ok": passed,
        "checks": checks,
        "n_bounce": n_bounce,
        "avg_r": avg_r,
        "exit": code,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", choices=("f0", "f1"))
    args = parser.parse_args(argv)
    code, payload = gate_f0() if args.gate == "f0" else gate_f1()
    out = repo_root() / "ops" / "gates"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"last_{args.gate}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

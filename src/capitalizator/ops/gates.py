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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", choices=("f0",))
    args = parser.parse_args(argv)
    code, payload = gate_f0()
    out = repo_root() / "ops" / "gates"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"last_{args.gate}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

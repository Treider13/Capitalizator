"""Read infra/phase.yaml. Bot does not write this file without a gate.

YAML 1.1 treats bare `off`/`none` as bool/null. Modes are quoted strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

MODES = frozenset({"off", "demo", "testnet", "shadow", "micro", "live"})
EQUITY = frozenset({"none", "demo", "micro_subaccount", "main"})


def phase_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "phase.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/phase.yaml missing")


def load_phase() -> dict[str, Any]:
    raw = yaml.safe_load(phase_path().read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("phase.yaml must be a mapping")
    return raw


def trading_mode() -> str:
    raw = load_phase().get("trading_mode")
    if raw is False or raw is None:
        return "off"
    text = str(raw)
    if text not in MODES:
        raise ValueError(f"unknown trading_mode: {raw!r}")
    return text


def equity_source() -> str:
    raw = load_phase().get("equity_source")
    if raw is None:
        return "none"
    text = str(raw)
    if text not in EQUITY:
        raise ValueError(f"unknown equity_source: {raw!r}")
    return text


def breakout_enabled() -> bool:
    raw = load_phase().get("breakout_enabled")
    if not isinstance(raw, bool):
        raise ValueError(f"breakout_enabled must be bool, got {raw!r}")
    return raw

"""Read infra/phase.yaml. Bot does not write this file without a gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


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
    return str(load_phase().get("trading_mode") or "off")

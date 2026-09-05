"""Frozen hyexec.yaml. Extra keys are an error. triple_and is not a live gate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

REQUIRED = (
    "identifier",
    "gate_mode",
    "probe_risk",
    "std_risk",
    "aplus_risk",
)
ALLOWED = frozenset(REQUIRED)
LIVE_GATE = "size_timing"
MAX_APLUS = Decimal("0.02")


class HyexecConfigError(ValueError):
    """hyexec.yaml is missing, has extra keys, or breaks the risk ceiling."""


@dataclass(frozen=True)
class HyexecConfig:
    identifier: str
    gate_mode: str
    probe_risk: Decimal
    std_risk: Decimal
    aplus_risk: Decimal


def _dec(raw: dict[str, Any], key: str) -> Decimal:
    try:
        value = Decimal(str(raw[key]))
    except Exception as exc:
        raise HyexecConfigError(f"{key} must be a decimal") from exc
    if value <= 0:
        raise HyexecConfigError(f"{key} must be > 0")
    return value


def load_hyexec(path: Path | str | None = None) -> HyexecConfig:
    src = Path(path) if path is not None else Path("infra/hyexec.yaml")
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise HyexecConfigError("hyexec must be a mapping")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise HyexecConfigError(f"missing keys: {missing}")
    extra = sorted(set(raw) - ALLOWED)
    if extra:
        raise HyexecConfigError(f"unknown keys (do not tune): {extra}")
    if raw["gate_mode"] != LIVE_GATE:
        raise HyexecConfigError("gate_mode must be size_timing")
    aplus = _dec(raw, "aplus_risk")
    if aplus > MAX_APLUS:
        raise HyexecConfigError("aplus_risk cannot exceed 0.02")
    probe = _dec(raw, "probe_risk")
    std = _dec(raw, "std_risk")
    if not (probe <= std <= aplus):
        raise HyexecConfigError("probe_risk <= std_risk <= aplus_risk")
    ident = str(raw["identifier"]).strip()
    if not ident:
        raise HyexecConfigError("identifier must be non-empty")
    return HyexecConfig(
        identifier=ident,
        gate_mode=LIVE_GATE,
        probe_risk=probe,
        std_risk=std,
        aplus_risk=aplus,
    )

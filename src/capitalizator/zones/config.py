"""Load infra/registry.yaml. Keys are the PHASE-BUILD freeze. No extra knobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED = (
    "epsilon_ticks",
    "bounce_away_ticks",
    "working_tf",
    "htf",
    "touch_pending_timeout_h",
    "die_no_touch_h",
    "zlg_window_s",
    "zlg_gamma",
    "prs_alpha",
    "prs_t_max_s",
    "prs_delta_ticks",
)


class RegistryConfigError(ValueError):
    """registry.yaml is missing or has extra/unknown knobs."""


@dataclass(frozen=True)
class RegistryConfig:
    epsilon_ticks: int
    bounce_away_ticks: int
    working_tf: str
    htf: str
    touch_pending_timeout_h: int
    die_no_touch_h: int
    zlg_window_s: int
    zlg_gamma: float
    prs_alpha: float
    prs_t_max_s: int
    prs_delta_ticks: int


def default_registry_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "registry.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/registry.yaml not found")


def load_registry(path: Path | None = None) -> RegistryConfig:
    raw = yaml.safe_load((path or default_registry_path()).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RegistryConfigError("registry must be a mapping")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise RegistryConfigError(f"missing keys: {missing}")
    extra = sorted(set(raw) - set(REQUIRED))
    if extra:
        raise RegistryConfigError(f"unknown keys (do not tune): {extra}")
    return RegistryConfig(
        epsilon_ticks=_int(raw, "epsilon_ticks"),
        bounce_away_ticks=_int(raw, "bounce_away_ticks"),
        working_tf=str(raw["working_tf"]),
        htf=str(raw["htf"]),
        touch_pending_timeout_h=_int(raw, "touch_pending_timeout_h"),
        die_no_touch_h=_int(raw, "die_no_touch_h"),
        zlg_window_s=_int(raw, "zlg_window_s"),
        zlg_gamma=float(raw["zlg_gamma"]),
        prs_alpha=float(raw["prs_alpha"]),
        prs_t_max_s=_int(raw, "prs_t_max_s"),
        prs_delta_ticks=_int(raw, "prs_delta_ticks"),
    )


def _int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryConfigError(f"{key} must be an int")
    return value

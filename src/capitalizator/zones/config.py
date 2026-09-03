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
    "htf_d1",
    "mid_band_ticks",
    "touch_pending_timeout_h",
    "die_no_touch_h",
    "zlg_window_s",
    "zlg_gamma",
    "prs_alpha",
    "prs_t_max_s",
    "prs_delta_ticks",
    "n_min",
    "mature_n",
)


class RegistryConfigError(ValueError):
    """registry.yaml is missing or has extra/unknown knobs."""


@dataclass(frozen=True)
class RegistryConfig:
    epsilon_ticks: int
    bounce_away_ticks: int
    working_tf: str
    htf: str
    htf_d1: str
    mid_band_ticks: int
    touch_pending_timeout_h: int
    die_no_touch_h: int
    zlg_window_s: int
    zlg_gamma: float
    prs_alpha: float
    prs_t_max_s: int
    prs_delta_ticks: int
    # "enough observations": a label/class may vote at n_min; a norm/interval is
    # narrow enough to refute at mature_n. One place for the whole desk (stats.py).
    n_min: int = 20
    mature_n: int = 30


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
        htf_d1=str(raw["htf_d1"]),
        mid_band_ticks=_int(raw, "mid_band_ticks"),
        touch_pending_timeout_h=_int(raw, "touch_pending_timeout_h"),
        die_no_touch_h=_int(raw, "die_no_touch_h"),
        zlg_window_s=_int(raw, "zlg_window_s"),
        zlg_gamma=float(raw["zlg_gamma"]),
        prs_alpha=float(raw["prs_alpha"]),
        prs_t_max_s=_int(raw, "prs_t_max_s"),
        prs_delta_ticks=_int(raw, "prs_delta_ticks"),
        n_min=_int(raw, "n_min"),
        mature_n=_int(raw, "mature_n"),
    )


def _int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryConfigError(f"{key} must be an int")
    return value

"""Load infra/registry.yaml. Keys are the PHASE-BUILD freeze. No extra knobs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

KNOWN_TFS = frozenset({"15m", "1h", "4h", "1d"})

REQUIRED = (
    "epsilon_ticks",
    "bounce_away_ticks",
    "working_tf",
    "mid_tf",
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
    "wall_min_notional",
    "wall_depth_mult",
)


class RegistryConfigError(ValueError):
    """registry.yaml is missing or has extra/unknown knobs."""


@dataclass(frozen=True)
class RegistryConfig:
    epsilon_ticks: int
    bounce_away_ticks: int
    working_tf: str
    mid_tf: str
    htf: str
    htf_d1: str

    @property
    def structure_tfs(self) -> tuple[str, ...]:
        """Working → mid → H4 → D1, unique. Every senior level pairs with the next down."""
        seen: list[str] = []
        for tf in (self.working_tf, self.mid_tf, self.htf, self.htf_d1):
            if tf not in seen:
                seen.append(tf)
        return tuple(seen)
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
    # Wall threshold before a symbol's Passport matures: one level worth this many USDT.
    wall_min_notional: Decimal = Decimal("3000000")
    # Wall threshold once the Passport is mature: one level ≥ mult × median zone-side depth.
    wall_depth_mult: Decimal = Decimal("1")


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
    cfg = RegistryConfig(
        epsilon_ticks=_int(raw, "epsilon_ticks"),
        bounce_away_ticks=_int(raw, "bounce_away_ticks"),
        working_tf=_tf(raw, "working_tf"),
        mid_tf=_tf(raw, "mid_tf"),
        htf=_tf(raw, "htf"),
        htf_d1=_tf(raw, "htf_d1"),
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
        wall_min_notional=_positive_decimal(raw, "wall_min_notional"),
        wall_depth_mult=_positive_decimal(raw, "wall_depth_mult"),
    )
    if len(cfg.structure_tfs) != 4:
        raise RegistryConfigError("working_tf/mid_tf/htf/htf_d1 must be four distinct TFs")
    return cfg


def _positive_decimal(raw: dict[str, Any], key: str) -> Decimal:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise RegistryConfigError(f"{key} must be a number")
    out = Decimal(str(value))
    if out <= 0:
        raise RegistryConfigError(f"{key} must be > 0")
    return out


def _int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryConfigError(f"{key} must be an int")
    return int(value)


def _tf(raw: dict[str, Any], key: str) -> str:
    value = str(raw[key])
    if value not in KNOWN_TFS:
        raise RegistryConfigError(f"{key} must be one of {sorted(KNOWN_TFS)}")
    return value

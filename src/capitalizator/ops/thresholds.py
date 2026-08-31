"""PHASE-BUILD infra/gates.yaml. Extra keys are an accident, not a silent knob."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TOP = frozenset({"f0", "f1", "f2", "f3", "f4", "f5"})
F0 = frozenset({"days", "symbols_strict", "unmarked_hours_max", "touches_min"})
F1 = frozenset({"n_bounce_demo_min", "avg_r_min", "average_attempts_max", "breakout_enabled"})
F2 = frozenset(
    {"veto_min", "cards_with_outcome_min", "against_btc_max", "veto_shadow_n_insufficient"}
)
F3 = frozenset(
    {
        "n_break_demo_min",
        "n_sum_demo_min",
        "avg_r_sum_min",
        "bounce_slack_r",
        "whale_entries_max",
        "failed_break_in_counts",
    }
)
F4 = frozenset(
    {
        "n_live_min",
        "weeks_min",
        "wr_hard",
        "wr_soft",
        "wr_cancel_900k",
        "wr_stop",
        "rr_min",
        "rr_min_wins",
        "rr_min_losses",
        "liq_max",
        "overlay",
    }
)
F4_OVERLAY = frozenset({"min_matched", "median_abs_r_diff_max", "same_sign_min"})
F5 = frozenset(
    {
        "target_risk",
        "target_risk_max_until_written_otherwise",
        "day_halt",
        "week_halt",
        "peak_kill",
    }
)
LEVELS = {
    "f0": F0,
    "f1": F1,
    "f2": F2,
    "f3": F3,
    "f4": F4,
    "f5": F5,
}


class GatesYamlError(ValueError):
    """gates.yaml is missing a required key or grew an unknown one."""


def gates_yaml_path(*, root: Path | None = None) -> Path:
    if root is not None:
        path = root / "infra" / "gates.yaml"
        if path.is_file():
            return path
        raise FileNotFoundError("infra/gates.yaml missing")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "gates.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/gates.yaml missing")


def load_gates(*, root: Path | None = None) -> dict[str, Any]:
    raw = yaml.safe_load(gates_yaml_path(root=root).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise GatesYamlError("gates.yaml must be a mapping")
    extra = set(raw) - TOP
    if extra:
        raise GatesYamlError(f"unknown gates.yaml keys: {sorted(extra)}")
    missing = TOP - set(raw)
    if missing:
        raise GatesYamlError(f"missing gates.yaml keys: {sorted(missing)}")
    for name, allowed in LEVELS.items():
        block = raw[name]
        if not isinstance(block, dict):
            raise GatesYamlError(f"{name} must be a mapping")
        extra_l = set(block) - allowed
        if extra_l:
            raise GatesYamlError(f"unknown {name} keys: {sorted(extra_l)}")
        miss_l = allowed - set(block)
        if miss_l:
            raise GatesYamlError(f"missing {name} keys: {sorted(miss_l)}")
    overlay = raw["f4"]["overlay"]
    if not isinstance(overlay, dict):
        raise GatesYamlError("f4.overlay must be a mapping")
    extra_o = set(overlay) - F4_OVERLAY
    if extra_o:
        raise GatesYamlError(f"unknown f4.overlay keys: {sorted(extra_o)}")
    miss_o = F4_OVERLAY - set(overlay)
    if miss_o:
        raise GatesYamlError(f"missing f4.overlay keys: {sorted(miss_o)}")
    if raw["f3"]["failed_break_in_counts"] is not False:
        raise GatesYamlError("failed_break_in_counts must stay false")
    if raw["f1"]["breakout_enabled"] is not False:
        raise GatesYamlError("f1.breakout_enabled must stay false until F2 pass")
    return raw

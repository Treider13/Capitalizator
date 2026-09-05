"""xgboost booster load/save/score. Contour A never imports this file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from capitalizator.hyexec.features import NAMES
from capitalizator.ops.vault import Vault, write_regular_bytes

MODEL_NAME = "hyexec_model.json"
XGB_PARAMS = {
    "objective": "reg:squarederror",
    "max_depth": 2,
    "eta": 0.2,
    "min_child_weight": 1,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "nthread": 1,
    "verbosity": 0,
}
NUM_ROUND = 25


def model_path(vault: Vault) -> Path:
    return vault.knowledge / MODEL_NAME


def fit(xs: list[list[float]], ys: list[float]) -> Any:
    import xgboost

    dmat = xgboost.DMatrix(xs, label=ys, feature_names=list(NAMES))
    return xgboost.train(XGB_PARAMS, dmat, num_boost_round=NUM_ROUND)


def save_booster(vault: Vault, booster: Any) -> Path:
    path = model_path(vault)
    raw = booster.save_raw(raw_format="json")
    write_regular_bytes(path, bytes(raw))
    return path


def load_booster(vault: Vault) -> Any | None:
    try:
        import xgboost
    except ImportError:
        return None
    path = model_path(vault)
    if not path.is_file():
        return None
    booster = xgboost.Booster()
    booster.load_model(str(path))
    return booster


def predict_one(booster: Any, vec: list[float]) -> float:
    import xgboost

    dmat = xgboost.DMatrix([vec], feature_names=list(NAMES))
    return float(booster.predict(dmat)[0])


def model_go(score: float) -> bool:
    """Send if predicted shadow R is above break-even. Same zero as class refute."""
    return score > 0

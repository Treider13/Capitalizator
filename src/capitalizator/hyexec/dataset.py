"""PIT matrix from journal hx_* columns. Does not fit. Contour A does not import this."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from capitalizator.champion.shadow_day import paper_r
from capitalizator.hyexec.features import NAMES

# Exam window is 15–20 trading days. One touch is one row. Fewer rows → no fit.
EXAM_MIN_ROWS = 15
FEATURE_KEYS = tuple(f"hx_{name}" for name in NAMES)


def can_fit(n: int) -> bool:
    return n >= EXAM_MIN_ROWS


def complete_n(rows: Sequence[Mapping[str, Any]]) -> int:
    """Rows whose hx_* vector has no hole. A None is a hole, not a zero."""
    return sum(1 for vec in matrix(rows) if all(v is not None for v in vec))


def labeled_pairs(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[list[float]], list[float]]:
    """Complete hx_* with a filled shadow r_net. The label is the paper outcome."""
    xs: list[list[float]] = []
    ys: list[float] = []
    for row, vec in zip(rows, matrix(rows), strict=True):
        if any(v is None for v in vec):
            continue
        r = paper_r(row, "shadow")
        if r is None:
            continue
        xs.append([float(v) for v in vec])
        ys.append(float(r))
    return xs, ys


def last_complete_by_symbol(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[float]]:
    """Newest complete hx_* per symbol. A row without symbol is not a desk key."""
    best: dict[str, tuple[str, list[float]]] = {}
    for row, vec in zip(rows, matrix(rows), strict=True):
        if any(v is None for v in vec):
            continue
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        ts = str(row.get("hyexec_as_of") or row.get("touch_ts") or "")
        if symbol not in best or ts >= best[symbol][0]:
            best[symbol] = (ts, [float(v) for v in vec])
    return {symbol: vec for symbol, (_ts, vec) in best.items()}


def last_complete(rows: Sequence[Mapping[str, Any]]) -> list[float] | None:
    """Newest complete hx_* vector. Missing as_of loses to a stamped row."""
    best: list[float] | None = None
    best_ts = ""
    for row, vec in zip(rows, matrix(rows), strict=True):
        if any(v is None for v in vec):
            continue
        ts = str(row.get("hyexec_as_of") or row.get("touch_ts") or "")
        if best is None or ts >= best_ts:
            best = [float(v) for v in vec]
            best_ts = ts
    return best


def plan_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = complete_n(rows)
    n_labeled = len(labeled_pairs(rows)[1])
    return {
        "n": n,
        "n_labeled": n_labeled,
        "n_rows": len(rows),
        "fit": can_fit(n_labeled),
    }


def matrix(rows: Sequence[Mapping[str, Any]]) -> list[list[float | None]]:
    """One row per touch. A missing hx_* stays None — no fill."""
    out: list[list[float | None]] = []
    for row in rows:
        vec: list[float | None] = []
        for key in FEATURE_KEYS:
            raw = row.get(key)
            if raw in {None, "", "null", "none"}:
                vec.append(None)
                continue
            vec.append(float(raw))
        out.append(vec)
    return out

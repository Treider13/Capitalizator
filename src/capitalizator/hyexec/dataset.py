"""PIT matrix from journal hx_* columns. Does not fit. Contour A does not import this."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from capitalizator.hyexec.features import NAMES

# Exam window is 15–20 trading days. One touch is one row. Fewer rows → no fit.
EXAM_MIN_ROWS = 15
FEATURE_KEYS = tuple(f"hx_{name}" for name in NAMES)


def can_fit(n: int) -> bool:
    return n >= EXAM_MIN_ROWS


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

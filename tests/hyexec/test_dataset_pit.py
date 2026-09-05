"""Journal hx_* is a PIT matrix. Too few rows → no fit. No invented fills."""

from __future__ import annotations

from capitalizator.hyexec.dataset import (
    EXAM_MIN_ROWS,
    FEATURE_KEYS,
    can_fit,
    complete_n,
    labeled_pairs,
    last_complete,
    matrix,
    plan_from_rows,
)
from capitalizator.hyexec.features import NAMES
from capitalizator.memory.journal import JOURNAL_KEYS, empty_journal


def test_exam_needs_fifteen_rows() -> None:
    assert EXAM_MIN_ROWS == 15
    assert can_fit(14) is False
    assert can_fit(15) is True


def test_journal_schema_has_hx_columns() -> None:
    blank = empty_journal()
    for key in FEATURE_KEYS:
        assert key in JOURNAL_KEYS
        assert blank[key] is None
    assert "hyexec_as_of" in JOURNAL_KEYS


def test_fifteen_holes_are_not_a_fit() -> None:
    holes = [{key: None for key in FEATURE_KEYS} for _ in range(15)]
    assert complete_n(holes) == 0
    assert can_fit(complete_n(holes)) is False


def test_complete_n_counts_only_full_vectors() -> None:
    full = {key: "1" for key in FEATURE_KEYS}
    hole = {key: "1" for key in FEATURE_KEYS}
    hole["hx_sma5_5m"] = None
    assert complete_n([full] * 14 + [hole]) == 14
    assert can_fit(complete_n([full] * 15)) is True


def test_labeled_pairs_need_shadow_r_net() -> None:
    full = {key: "1" for key in FEATURE_KEYS}
    full["paper"] = {"shadow": {"filled": True, "r_net": "1.25"}}
    hole = {key: "1" for key in FEATURE_KEYS}
    hole["paper"] = {"shadow": {"filled": True, "r_net": "2"}}
    hole["hx_sma5_5m"] = None
    xs, ys = labeled_pairs([full, hole, {key: "1" for key in FEATURE_KEYS}])
    assert xs == [[1.0] * len(FEATURE_KEYS)]
    assert ys == [1.25]
    plan = plan_from_rows([full] * 15)
    assert plan["n_labeled"] == 15
    assert plan["fit"] is True


def test_last_complete_prefers_newest_as_of() -> None:
    older = {key: "1" for key in FEATURE_KEYS}
    older["hyexec_as_of"] = "2026-09-01T10:00:00+00:00"
    newer = {key: "2" for key in FEATURE_KEYS}
    newer["hyexec_as_of"] = "2026-09-01T10:05:00+00:00"
    assert last_complete([older, newer]) == [2.0] * len(FEATURE_KEYS)


def test_matrix_keeps_none_no_fill() -> None:
    row = {f"hx_{name}": None for name in NAMES}
    row["hx_close_5m"] = "100.5"
    got = matrix([row])
    assert len(got[0]) == len(NAMES)
    close_i = NAMES.index("close_5m")
    assert got[0][close_i] == 100.5
    assert got[0][NAMES.index("sma5_5m")] is None

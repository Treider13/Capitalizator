"""Journal hx_* is a PIT matrix. Too few rows → no fit. No invented fills."""

from __future__ import annotations

from capitalizator.hyexec.dataset import EXAM_MIN_ROWS, FEATURE_KEYS, can_fit, matrix
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


def test_matrix_keeps_none_no_fill() -> None:
    row = {f"hx_{name}": None for name in NAMES}
    row["hx_close_5m"] = "100.5"
    got = matrix([row])
    assert len(got[0]) == len(NAMES)
    close_i = NAMES.index("close_5m")
    assert got[0][close_i] == 100.5
    assert got[0][NAMES.index("sma5_5m")] is None

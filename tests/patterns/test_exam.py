"""Hostile exam: last-price, ATR residual, 5-day PnL share, direction ≠ vol."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from capitalizator.patterns.exam import ExamCase, hostile_exam

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "patterns" / "exam.py"


def test_empty_sample_is_none() -> None:
    out = hostile_exam([])
    assert out.n == 0
    assert out.beat_last_price is None
    assert out.direction_hit is None
    assert out.vol_rank_ic is None


def test_pred_worse_than_last_price_does_not_beat() -> None:
    rows = [
        ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10")),
        ExamCase(pred=Decimal("8"), last=Decimal("10"), actual=Decimal("10")),
    ]
    out = hostile_exam(rows)
    assert out.n == 2
    assert out.beat_last_price == Decimal("0")


def test_exact_next_close_beats_last_price() -> None:
    rows = [ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("11"))]
    assert hostile_exam(rows).beat_last_price == Decimal("1")


def test_equal_error_is_not_a_last_price_beat() -> None:
    """Tie is not a beat. `<=` would count this as 1."""
    rows = [ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("10.5"))]
    assert abs(rows[0].pred - rows[0].actual) == abs(rows[0].last - rows[0].actual)
    assert hostile_exam(rows).beat_last_price == Decimal("0")


def test_zero_atr_is_excluded_from_residual() -> None:
    """atr=0 is not a divisor. Including it is ZeroDivision or a fake residual."""
    rows = [ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("0"))]
    assert hostile_exam(rows).residual_after_atr is None
    only_none = [ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=None)]
    assert hostile_exam(only_none).residual_after_atr is None


def test_residual_is_median_error_over_atr() -> None:
    rows = [
        ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
        ExamCase(pred=Decimal("10"), last=Decimal("10"), actual=Decimal("10"), atr=None),
    ]
    assert hostile_exam(rows).residual_after_atr == Decimal("0.75")


def test_pnl_share_needs_five_days_and_positive_total() -> None:
    four = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 1, d), pnl=Decimal("1"))
        for d in range(1, 5)
    ]
    assert hostile_exam(four).pnl_share_best_5_days is None
    days = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 1, d), pnl=pnl)
        for d, pnl in (
            (1, Decimal("91")),
            (2, Decimal("1")),
            (3, Decimal("1")),
            (4, Decimal("1")),
            (5, Decimal("1")),
            (6, Decimal("5")),
        )
    ]
    share = hostile_exam(days).pnl_share_best_5_days
    assert share == Decimal("99") / Decimal("100")
    lost = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 2, d), pnl=Decimal("-1"))
        for d in range(1, 6)
    ]
    assert hostile_exam(lost).pnl_share_best_5_days is None


def test_direction_and_vol_rank_are_separate() -> None:
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("0.9"),
            actual_vol=Decimal("1"),
        ),
        ExamCase(
            pred=Decimal("9"),
            last=Decimal("10"),
            actual=Decimal("8"),
            pred_vol_rank=Decimal("0.1"),
            actual_vol=Decimal("9"),
        ),
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("0.8"),
            actual_vol=Decimal("2"),
        ),
        ExamCase(
            pred=Decimal("9"),
            last=Decimal("10"),
            actual=Decimal("8"),
            pred_vol_rank=Decimal("0.2"),
            actual_vol=Decimal("8"),
        ),
    ]
    out = hostile_exam(rows)
    assert out.direction_hit == Decimal("1")
    assert out.vol_rank_ic is not None
    assert out.vol_rank_ic < 0


def test_two_runs_bit_identical() -> None:
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("11"),
            atr=Decimal("2"),
            day=date(2026, 1, 1),
            pnl=Decimal("1"),
            pred_vol_rank=Decimal("0.4"),
            actual_vol=Decimal("3"),
        ),
        ExamCase(
            pred=Decimal("9"),
            last=Decimal("10"),
            actual=Decimal("9"),
            atr=Decimal("2"),
            day=date(2026, 1, 2),
            pnl=Decimal("2"),
            pred_vol_rank=Decimal("0.6"),
            actual_vol=Decimal("4"),
        ),
    ]

    def run() -> tuple[object, ...]:
        out = hostile_exam(rows)
        return (
            out.n,
            out.beat_last_price,
            out.residual_after_atr,
            out.pnl_share_best_5_days,
            out.direction_hit,
            out.vol_rank_ic,
        )

    assert run() == run()


def test_one_vol_pair_is_not_an_ic() -> None:
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("1"),
            actual_vol=Decimal("2"),
        )
    ]
    assert hostile_exam(rows).vol_rank_ic is None


def test_pnl_without_day_does_not_unlock_share() -> None:
    """A print with pnl and no day is not a fifth day."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 5, d), pnl=Decimal("1"))
        for d in range(1, 5)
    ]
    rows.append(ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=None, pnl=Decimal("100")))
    assert len(rows) == 5
    assert hostile_exam(rows).pnl_share_best_5_days is None


def test_no_predicted_direction_is_none() -> None:
    rows = [ExamCase(pred=Decimal("10"), last=Decimal("10"), actual=Decimal("11"))]
    assert hostile_exam(rows).direction_hit is None


def test_flat_actual_is_a_direction_miss() -> None:
    rows = [ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("10"))]
    assert hostile_exam(rows).direction_hit == Decimal("0")


def test_vol_rank_ic_is_plus_one_and_minus_one() -> None:
    up = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal(i),
            actual_vol=Decimal(i),
        )
        for i in range(1, 5)
    ]
    down = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal(i),
            actual_vol=Decimal(5 - i),
        )
        for i in range(1, 5)
    ]
    up_ic = hostile_exam(up).vol_rank_ic
    down_ic = hostile_exam(down).vol_rank_ic
    assert up_ic is not None and down_ic is not None
    # Decimal.sqrt is not bit-exact; do not pretend the IC is exactly ±1.
    assert Decimal("0.999") < up_ic <= 1
    assert -1 <= down_ic < Decimal("-0.999")


def test_pnl_share_needs_five_unique_days_not_five_cases() -> None:
    """5 prints on 4 calendar days must not unlock the share."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 4, d), pnl=Decimal("1"))
        for d in (1, 1, 2, 3, 4)
    ]
    assert len(rows) == 5
    assert len({c.day for c in rows}) == 4
    assert hostile_exam(rows).pnl_share_best_5_days is None


def test_pnl_share_sums_two_prints_on_the_same_day() -> None:
    """Last write on a day would change 99/100 if the fat day was split 90+1."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 1, d), pnl=pnl)
        for d, pnl in (
            (1, Decimal("90")),
            (1, Decimal("1")),
            (2, Decimal("1")),
            (3, Decimal("1")),
            (4, Decimal("1")),
            (5, Decimal("1")),
            (6, Decimal("5")),
        )
    ]
    assert hostile_exam(rows).pnl_share_best_5_days == Decimal("99") / Decimal("100")


def test_pnl_share_can_exceed_one_when_a_day_loses() -> None:
    days = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 3, d), pnl=pnl)
        for d, pnl in (
            (1, Decimal("91")),
            (2, Decimal("1")),
            (3, Decimal("1")),
            (4, Decimal("1")),
            (5, Decimal("1")),
            (6, Decimal("-20")),
        )
    ]
    share = hostile_exam(days).pnl_share_best_5_days
    assert share == Decimal("95") / Decimal("75")
    assert share > 1


def test_exam_source_has_no_numpy() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "import numpy" not in text
    assert "from numpy" not in text
    assert "import np" not in text

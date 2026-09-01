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


def test_one_hit_one_miss_is_half() -> None:
    rows = [
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("12")),
        ExamCase(pred=Decimal("9"), last=Decimal("10"), actual=Decimal("11")),
    ]
    assert hostile_exam(rows).direction_hit == Decimal("1") / Decimal("2")


def test_direction_hit_uses_the_whole_sample() -> None:
    """Last-2 of hit,miss,hit is 1/2. The sample is 2/3."""
    rows = [
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("12")),
        ExamCase(pred=Decimal("9"), last=Decimal("10"), actual=Decimal("11")),
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("12")),
    ]
    assert hostile_exam(rows).direction_hit == Decimal("2") / Decimal("3")


def test_actual_between_last_and_pred_is_a_direction_hit() -> None:
    """Direction is vs last, not vs pred. 10→10.5 with pred 11 is a hit; vs pred it is a miss."""
    up = ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("10.5"))
    down = ExamCase(pred=Decimal("9"), last=Decimal("10"), actual=Decimal("9.5"))
    assert Decimal("10") < up.actual < up.pred
    assert down.pred < down.actual < Decimal("10")
    assert hostile_exam([up]).direction_hit == Decimal("1")
    assert hostile_exam([down]).direction_hit == Decimal("1")
    assert hostile_exam([up]).beat_last_price == Decimal("0")


def test_zero_atr_is_excluded_from_residual() -> None:
    """atr=0 is not a divisor. Including it is ZeroDivision or a fake residual."""
    rows = [ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("0"))]
    assert hostile_exam(rows).residual_after_atr is None
    only_none = [ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=None)]
    assert hostile_exam(only_none).residual_after_atr is None
    neg = [ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("-1"))]
    assert hostile_exam(neg).residual_after_atr is None


def test_residual_of_one_value_is_that_value() -> None:
    rows = [ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2"))]
    assert hostile_exam(rows).residual_after_atr == Decimal("1")


def test_residual_is_median_error_over_atr() -> None:
    rows = [
        ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
        ExamCase(pred=Decimal("10"), last=Decimal("10"), actual=Decimal("10"), atr=None),
    ]
    assert hostile_exam(rows).residual_after_atr == Decimal("0.75")


def test_residual_median_uses_the_whole_sample() -> None:
    """Last-5 of 1,2,3,4,5,100 is 4. First-5 is 3. All six even-n median is 3.5."""
    rows = [
        ExamCase(pred=Decimal(str(10 + err)), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("1"))
        for err in (1, 2, 3, 4, 5, 100)
    ]
    assert hostile_exam(rows).residual_after_atr == Decimal("3.5")


def test_residual_median_is_not_the_mean() -> None:
    """Two residuals share a mean and a median. Mean of 1, 2, 10 is 13/3, not 2."""
    rows = [
        ExamCase(pred=Decimal("12"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
        ExamCase(pred=Decimal("14"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
        ExamCase(pred=Decimal("30"), last=Decimal("10"), actual=Decimal("10"), atr=Decimal("2")),
    ]
    assert hostile_exam(rows).residual_after_atr == Decimal("2")
    assert sum((Decimal("1"), Decimal("2"), Decimal("10"))) / Decimal("3") != Decimal("2")


def test_last_price_beat_uses_the_whole_sample() -> None:
    """Last-2 of beat,miss,beat is 1/2. The sample is 2/3."""
    rows = [
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("11")),
        ExamCase(pred=Decimal("9"), last=Decimal("10"), actual=Decimal("11")),
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("11")),
    ]
    assert hostile_exam(rows).beat_last_price == Decimal("2") / Decimal("3")


def test_last_price_tie_stays_in_the_beat_denominator() -> None:
    """One beat + one equal error is 1/2. Dropping ties from n would report 1."""
    rows = [
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("11")),
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("10.5")),
    ]
    assert abs(rows[1].pred - rows[1].actual) == abs(rows[1].last - rows[1].actual)
    assert hostile_exam(rows).beat_last_price == Decimal("1") / Decimal("2")


def test_five_zero_pnl_days_have_no_share() -> None:
    """total=0 is not a share. Returning 0 would look like 'no concentration'."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 7, d), pnl=Decimal("0"))
        for d in range(1, 6)
    ]
    assert hostile_exam(rows).pnl_share_best_5_days is None


def test_mixed_net_zero_five_days_have_no_share() -> None:
    """All-zero days already fail. +10×4 −40 is also total=0 — `total < 0` only would divide by zero."""
    pnls = (Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("-40"))
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 7, d), pnl=pnl)
        for d, pnl in zip(range(1, 6), pnls)
    ]
    assert sum(pnls, Decimal("0")) == Decimal("0")
    assert hostile_exam(rows).pnl_share_best_5_days is None


def test_five_days_including_a_loss_still_unlock() -> None:
    """Floor is 5 calendar days, not 5 winning days. Top-5 of 5 is the whole book → share 1."""
    pnls = (Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("-5"))
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 9, d), pnl=pnl)
        for d, pnl in zip(range(1, 6), pnls)
    ]
    share = hostile_exam(rows).pnl_share_best_5_days
    assert share == Decimal("1")


def test_pnl_share_unlocks_on_exactly_five_days() -> None:
    """Success fixtures use 6 days. `len(by_day) < 6` would still pass those."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 8, d), pnl=Decimal("1"))
        for d in range(1, 6)
    ]
    assert len({c.day for c in rows}) == 5
    assert hostile_exam(rows).pnl_share_best_5_days == Decimal("1")


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


def test_two_vol_pairs_unlock_ic() -> None:
    """Success fixtures use 4 pairs. `len(pairs) < 3` would still pass those."""
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("1"),
            actual_vol=Decimal("1"),
        ),
        ExamCase(
            pred=Decimal("9"),
            last=Decimal("10"),
            actual=Decimal("8"),
            pred_vol_rank=Decimal("2"),
            actual_vol=Decimal("2"),
        ),
    ]
    ic = hostile_exam(rows).vol_rank_ic
    assert ic is not None
    assert Decimal("0.999") < ic < Decimal("1.002")


def test_vol_rank_ic_is_spearman_not_raw_pearson() -> None:
    """1,2,100 vs 1,2,3 is monotone: Spearman ≈ 1. Pearson on raw values is ~0.87."""
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal(p),
            actual_vol=Decimal(a),
        )
        for p, a in ((1, 1), (2, 2), (100, 3))
    ]
    ic = hostile_exam(rows).vol_rank_ic
    assert ic is not None
    # Decimal.sqrt is not bit-exact; this triple can land a hair above 1.
    assert Decimal("0.999") < ic < Decimal("1.002")


def test_vol_rank_ic_is_spearman_not_kendall() -> None:
    """Ranks 1,2,3,4 vs 1,2,4,3: Spearman 0.8. Kendall tau is 2/3."""
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal(p),
            actual_vol=Decimal(a),
        )
        for p, a in ((1, 1), (2, 2), (3, 4), (4, 3))
    ]
    ic = hostile_exam(rows).vol_rank_ic
    assert ic is not None
    assert Decimal("0.799") < ic < Decimal("0.801")


def test_vol_rank_ic_uses_average_ranks_for_a_partial_tie() -> None:
    """pred 1,2,2,3 vs actual 1,2,3,4. Midranks 1,2.5,2.5,4. List-order 1,2,3,4 is IC=1.

    Competition ranks 1,2,2,4 land near 0.923. Average-rank Spearman is ~0.949.
    """
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal(p),
            actual_vol=Decimal(a),
        )
        for p, a in ((1, 1), (2, 2), (2, 3), (3, 4))
    ]
    ic = hostile_exam(rows).vol_rank_ic
    assert ic is not None
    assert ic != Decimal("1")
    assert Decimal("0.94") < ic < Decimal("0.96")


def test_pnl_without_day_does_not_unlock_share() -> None:
    """A print with pnl and no day is not a fifth day."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 5, d), pnl=Decimal("1"))
        for d in range(1, 5)
    ]
    rows.append(ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=None, pnl=Decimal("100")))
    assert len(rows) == 5
    assert hostile_exam(rows).pnl_share_best_5_days is None


def test_flat_pred_is_excluded_from_direction_denominator() -> None:
    """One hit + one pred==last is 1/1, not 1/2."""
    rows = [
        ExamCase(pred=Decimal("11"), last=Decimal("10"), actual=Decimal("12")),
        ExamCase(pred=Decimal("10"), last=Decimal("10"), actual=Decimal("12")),
    ]
    assert hostile_exam(rows).direction_hit == Decimal("1")


def test_incomplete_vol_pair_is_not_a_second_point() -> None:
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("1"),
            actual_vol=Decimal("2"),
        ),
        ExamCase(
            pred=Decimal("9"),
            last=Decimal("10"),
            actual=Decimal("8"),
            pred_vol_rank=Decimal("0.2"),
            actual_vol=None,
        ),
    ]
    assert hostile_exam(rows).n == 2
    assert hostile_exam(rows).vol_rank_ic is None


def test_day_with_pnl_none_is_not_a_fifth_day() -> None:
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 6, d), pnl=Decimal("1"))
        for d in range(1, 5)
    ]
    rows.append(ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 6, 5), pnl=None))
    assert len({c.day for c in rows}) == 5
    assert hostile_exam(rows).pnl_share_best_5_days is None


def test_tied_pred_ranks_have_no_ic() -> None:
    """Average ranks of a tie have zero variance. Ordinal 1,2 would invent a ±1 IC here."""
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("1"),
            actual_vol=Decimal("1"),
        ),
        ExamCase(
            pred=Decimal("9"),
            last=Decimal("10"),
            actual=Decimal("8"),
            pred_vol_rank=Decimal("1"),
            actual_vol=Decimal("9"),
        ),
    ]
    assert rows[0].pred_vol_rank == rows[1].pred_vol_rank
    assert rows[0].actual_vol != rows[1].actual_vol
    assert hostile_exam(rows).vol_rank_ic is None


def test_flat_vol_ranks_have_no_ic() -> None:
    rows = [
        ExamCase(
            pred=Decimal("11"),
            last=Decimal("10"),
            actual=Decimal("12"),
            pred_vol_rank=Decimal("1"),
            actual_vol=Decimal("5"),
        )
        for _ in range(3)
    ]
    assert hostile_exam(rows).vol_rank_ic is None


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
    assert Decimal("0.999") < up_ic < Decimal("1.002")
    assert Decimal("-1.002") < down_ic < Decimal("-0.999")


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


def test_six_equal_days_share_is_five_sixths() -> None:
    """Best 5 of 6 identical days is 5/6. 'All tied so share=1' or the whole book would report 1."""
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 10, d), pnl=Decimal("10"))
        for d in range(1, 7)
    ]
    assert hostile_exam(rows).pnl_share_best_5_days == Decimal("50") / Decimal("60")


def test_pnl_share_tie_for_fifth_does_not_include_the_sixth() -> None:
    """Two days tied for 5th: still exactly 5 days in the numerator, not 6."""
    pnls = (
        Decimal("10"),
        Decimal("10"),
        Decimal("10"),
        Decimal("10"),
        Decimal("5"),
        Decimal("5"),
    )
    rows = [
        ExamCase(pred=Decimal("1"), last=Decimal("1"), actual=Decimal("1"), day=date(2026, 11, d), pnl=pnl)
        for d, pnl in zip(range(1, 7), pnls)
    ]
    share = hostile_exam(rows).pnl_share_best_5_days
    assert share == Decimal("45") / Decimal("50")
    assert share != Decimal("1")


def test_exam_source_has_no_numpy() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "import numpy" not in text
    assert "from numpy" not in text
    assert "import np" not in text

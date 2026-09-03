"""D-03: classes are refuted by data (Wilson upper bound < break-even), never by a count."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.champion.calibrate import (
    MIN_N,
    ClassStat,
    class_key,
    class_stats,
    refuted,
    to_meta,
    wilson,
)


def _row(tag: str, cav: str, zlg: str, r: str, filled: bool = True) -> dict:
    return {
        "tag": tag, "entry_px": "100" if filled else None, "r_net": r if filled else None,
        "labels": {"cav_label": cav, "zlg_label": zlg},
    }


def test_wilson_matches_known_values() -> None:
    lo, hi = wilson(5, 10)
    assert Decimal("0.23") < lo < Decimal("0.24") and Decimal("0.76") < hi < Decimal("0.77")
    lo0, hi0 = wilson(0, 30)
    assert lo0 < Decimal("1e-20") and Decimal("0.11") < hi0 < Decimal("0.12")  # Decimal rounding noise
    with pytest.raises(ValueError):
        wilson(0, 0)


def test_class_stats_ignore_unfilled_and_group_by_labels() -> None:
    rows = [_row("bounce", "REJECT", "DEFEND", "1.5"), _row("bounce", "REJECT", "DEFEND", "-1.1"),
            _row("bounce", "REJECT", "DEFEND", "0.2", filled=False), _row("spring", "REJECT", "DEFEND", "2")]
    stats = class_stats(rows)
    key = class_key(idea="bounce", cav="REJECT", zlg="DEFEND")
    assert stats[key].n == 2 and stats[key].wins == 1 and stats[key].winrate == Decimal("0.5")
    assert stats[class_key(idea="spring", cav="REJECT", zlg="DEFEND")].n == 1
    assert '"n": 2' in to_meta(stats)


def test_refuted_needs_n_and_a_losing_upper_bound() -> None:
    breakeven = Decimal("0.36")  # ≈ (R + c) / 3R for a 2R target
    thin = class_stats([_row("bounce", "REJECT", "DEFEND", "-1")] * 10)
    assert refuted(next(iter(thin.values())), breakeven=breakeven) is False  # n < 30
    losers = class_stats([_row("bounce", "REJECT", "DEFEND", "-1")] * 30 + [_row("bounce", "REJECT", "DEFEND", "1")] * 2)
    stat = next(iter(losers.values()))
    assert stat.n == 32 and stat.upper < breakeven
    assert refuted(stat, breakeven=breakeven) is True
    coin = class_stats([_row("bounce", "REJECT", "DEFEND", "-1")] * 20 + [_row("bounce", "REJECT", "DEFEND", "1")] * 20)
    assert refuted(next(iter(coin.values())), breakeven=breakeven) is False  # 50% is above break-even
    assert refuted(None, breakeven=breakeven) is False
    assert MIN_N == 30
    assert isinstance(stat, ClassStat)

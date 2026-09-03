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


def test_refuted_is_about_mean_net_r_not_winrate() -> None:
    """Audit B6: 60% "wins" of +0.3R and 40% losses of −1R lose money; the old rule
    (winrate upper bound vs a 2R break-even) passed such a class."""
    from decimal import Decimal

    from capitalizator.champion.calibrate import class_stats, refuted

    rows = []
    for i in range(60):
        rows.append({"entry_px": "1", "r_net": "0.3", "tag": "bounce",
                     "labels": {"cav_label": "REJECT", "zlg_label": "DEFEND"}})
    for i in range(40):
        rows.append({"entry_px": "1", "r_net": "-1", "tag": "bounce",
                     "labels": {"cav_label": "REJECT", "zlg_label": "DEFEND"}})
    stat = class_stats(rows)["bounce|REJECT|DEFEND"]
    assert stat.winrate == Decimal("0.6") and stat.avg_r_net < 0
    assert stat.upper_r_net is not None and stat.upper_r_net < 0
    assert refuted(stat) is True
    # a genuinely positive class is not refuted
    good = class_stats([{"entry_px": "1", "r_net": "1.5" if i % 2 else "-1", "tag": "bounce",
                         "labels": {"cav_label": "REJECT", "zlg_label": "DEFEND"}} for i in range(60)])
    assert refuted(good["bounce|REJECT|DEFEND"]) is False
    # too few observations: never refuted
    few = class_stats(rows[:10])
    assert refuted(few["bounce|REJECT|DEFEND"]) is False

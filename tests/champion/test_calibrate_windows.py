"""Sessions release: class stats per window / symbol group, lookup fallback, eligible
windows (lower bound clears break-even), k_atr from the MAE of winning paper trades."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.champion.calibrate import (
    ELIGIBLE_MIN_N,
    class_key,
    class_stats,
    eligible,
    eligible_windows,
    k_atr_by_window,
    legacy_key,
    lookup,
    refuted,
    window_key,
)


def _row(r: str, *, window: str | None = "overlap", group: str | None = "majors",
         atr: str | None = "100", mae: str = "99.5", filled: bool = True) -> dict:
    labels = {"cav_label": "REJECT", "zlg_label": "DEFEND"}
    if window is not None:
        labels["window"] = window
    if group is not None:
        labels["symbol_group"] = group
    if atr is not None:
        labels["atr"] = atr
    return {"tag": "bounce", "entry_px": "100" if filled else None, "r_net": r if filled else None,
            "mae_px": mae, "labels": labels}


def test_keys_have_five_parts_and_aggregate_with_star() -> None:
    full = class_key(idea="bounce", cav="REJECT", zlg="DEFEND", window="asia", group="rest")
    assert full == "bounce|REJECT|DEFEND|asia|rest"
    assert window_key(full) == "bounce|REJECT|DEFEND|asia|*"
    assert legacy_key(full) == "bounce|REJECT|DEFEND|*|*"
    assert class_key(idea="bounce", cav="REJECT", zlg="DEFEND") == "bounce|REJECT|DEFEND|*|*"


def test_stats_are_kept_at_three_granularities() -> None:
    rows = [_row("1")] * 3 + [_row("-1", group="top10")] * 2 + [_row("1", window=None, group=None)]
    stats = class_stats(rows)
    assert stats["bounce|REJECT|DEFEND|overlap|majors"].n == 3
    assert stats["bounce|REJECT|DEFEND|overlap|top10"].n == 2
    assert stats["bounce|REJECT|DEFEND|overlap|*"].n == 5
    assert stats["bounce|REJECT|DEFEND|*|*"].n == 6  # rows without a window only feed legacy


def test_lookup_prefers_the_most_specific_class_with_enough_data() -> None:
    rows = [_row("-1")] * 10 + [_row("1", group="top10")] * 25
    stats = class_stats(rows)
    key = "bounce|REJECT|DEFEND|overlap|majors"
    # majors has 10 (< MIN_N) → fall back to the window aggregate (35)
    assert lookup(stats, key).n == 35 and lookup(stats, key).key == window_key(key)
    # a class never seen at all → None
    assert lookup(stats, "spring|THROUGH|RETREAT|asia|rest") is None
    # a thin full class with nothing bigger → the thin one is returned (not refutable)
    thin = class_stats([_row("-1", window="night", group="rest")] * 5)
    got = lookup(thin, "bounce|REJECT|DEFEND|night|rest")
    assert got is not None and got.n == 5
    assert refuted(got, breakeven=Decimal("0.4")) is False


def test_eligible_needs_forty_and_a_winning_lower_bound() -> None:
    breakeven = Decimal("0.4")
    good = class_stats([_row("1", window="night")] * 32 + [_row("-1", window="night")] * 8)
    stat = good["bounce|REJECT|DEFEND|night|*"]
    assert stat.n == ELIGIBLE_MIN_N == 40 and stat.lower > breakeven
    assert eligible(stat, breakeven=breakeven) is True
    coin = class_stats([_row("1", window="night")] * 20 + [_row("-1", window="night")] * 20)
    assert eligible(coin["bounce|REJECT|DEFEND|night|*"], breakeven=breakeven) is False
    thin = class_stats([_row("1", window="night")] * 39)
    assert eligible(thin["bounce|REJECT|DEFEND|night|*"], breakeven=breakeven) is False
    flagged = eligible_windows(good, breakeven=breakeven, closed_windows=["night", "weekend"])
    assert flagged == {"night": ["bounce|REJECT|DEFEND|night|*"]}
    # an open window is never "eligible" — it is already trading
    assert eligible_windows(good, breakeven=breakeven, closed_windows=["asia"]) == {}


def test_loss_series_and_median_hold_by_window() -> None:
    from capitalizator.champion.calibrate import loss_series_by_window, median_hold_hours

    rows = []
    for i in range(35):
        r = dict(_row("1" if i % 2 else "-1", window="asia"))
        r["closed_at"] = f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00"
        r["hold_s"] = str(3600 * (i + 1))  # 1h … 35h
        rows.append(r)
    rows.append(dict(_row("1", window=None)))  # no window → not in any series
    series = loss_series_by_window(rows)
    assert set(series) == {"asia"} and len(series["asia"]) == 35
    assert set(series["asia"]) == {0, 1}
    hold = median_hold_hours(rows)
    assert hold == {"bounce|asia": Decimal(18)}
    # below MIN_N → no estimate
    assert median_hold_hours(rows[:10]) == {}


def test_k_atr_by_window_is_the_p90_of_winning_mae_over_atr() -> None:
    rows = []
    for i in range(40):
        # winners with MAE spread 0.10 … 0.49 ATR; losers are ignored
        rows.append(_row("1.5", window="asia", atr="100", mae=str(100 - (10 + i) / 100 * 100)))
    rows += [_row("-1", window="asia", atr="100", mae="60")] * 30
    rows += [_row("1", window="overlap", atr="100", mae="80")] * 10  # n < 30 → no estimate
    out = k_atr_by_window(rows)
    assert set(out) == {"asia"}
    assert Decimal("0.44") <= out["asia"] <= Decimal("0.49")
    # no ATR label → skipped, not guessed
    assert k_atr_by_window([_row("1", window="europe", atr=None)] * 40) == {}

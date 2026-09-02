"""Forecast: shrinkage chain, n<20 abstains, exact LOO conformal set, coverage."""

from __future__ import annotations

import random

import pytest

from capitalizator.oko.forecast import (
    KAPPA,
    N_MIN,
    OUTCOMES,
    Sample,
    class_key,
    forecast,
)

KEY = class_key(idea="bounce", cav="REJECT", zlg="DEFEND", regime="RANGE")


def _rows(outcomes: list[str], *, symbol: str = "BTCUSDT", key: str = KEY) -> list[Sample]:
    return [Sample(symbol=symbol, class_key=key, outcome=o) for o in outcomes]


def test_class_key_marks_missing_labels() -> None:
    assert KEY == "bounce × REJECT × DEFEND × RANGE × ?"
    assert (
        class_key(idea="breakout", cav=None, zlg="RETREAT", regime=None)
        == "breakout × ? × RETREAT × ? × ?"
    )
    full = class_key(idea="bounce", cav="REJECT", zlg="DEFEND", regime="RANGE", footprint="ABSORB")
    assert full == "bounce × REJECT × DEFEND × RANGE × ABSORB"
    with pytest.raises(ValueError):
        class_key(idea="scalp", cav=None, zlg=None, regime=None)


def test_empty_history_is_uniform_and_abstains() -> None:
    rep = forecast([], symbol="BTCUSDT", key=KEY)
    assert rep.n_class == rep.n_symbol == rep.n_global == 0
    assert all(abs(rep.p[y] - 1 / 3) < 1e-12 for y in OUTCOMES)
    assert rep.pred_set == frozenset(OUTCOMES)
    assert rep.decisive is None
    assert rep.q_hat is None


def test_below_n_min_never_decisive_even_if_unanimous() -> None:
    rep = forecast(_rows(["bounce"] * (N_MIN - 1)), symbol="BTCUSDT", key=KEY)
    assert rep.n_class == N_MIN - 1
    assert rep.p["bounce"] > 0.6
    assert rep.pred_set == frozenset(OUTCOMES)
    assert rep.decisive is None


def test_unanimous_class_at_n_min_is_decisive() -> None:
    rep = forecast(_rows(["bounce"] * 25), symbol="BTCUSDT", key=KEY)
    assert rep.decisive == "bounce"
    assert rep.pred_set == frozenset({"bounce"})
    assert rep.q_hat is not None
    assert rep.set_text == "bounce"


def test_mixed_class_gives_a_two_outcome_set() -> None:
    rep = forecast(_rows(["bounce"] * 14 + ["break"] * 11), symbol="BTCUSDT", key=KEY)
    assert rep.decisive is None
    assert {"bounce", "break"} <= rep.pred_set
    assert abs(sum(rep.p.values()) - 1.0) < 1e-12


def test_die_singleton_is_not_decisive() -> None:
    rep = forecast(_rows(["die"] * 30), symbol="BTCUSDT", key=KEY)
    assert rep.pred_set == frozenset({"die"})
    assert rep.decisive is None


def test_shrinkage_chain_hand_computed() -> None:
    """Global 10 bounce; symbol adds 10 break in another class; our class empty."""
    rows = _rows(["bounce"] * 10, symbol="ETHUSDT") + _rows(
        ["break"] * 10, key="bounce × THROUGH × RETREAT × RANGE"
    )
    rep = forecast(rows, symbol="BTCUSDT", key=KEY)
    k = KAPPA
    g = {y: (10 * (y == "bounce") + 10 * (y == "break") + k / 3) / (20 + k) for y in OUTCOMES}
    s = {y: (10 * (y == "break") + k * g[y]) / (10 + k) for y in OUTCOMES}
    c = {y: (0 + k * s[y]) / (0 + k) for y in OUTCOMES}
    for y in OUTCOMES:
        assert abs(rep.p[y] - c[y]) < 1e-12
    assert rep.n_class == 0 and rep.n_symbol == 10 and rep.n_global == 20
    assert rep.p["break"] > rep.p["bounce"] > rep.p["die"]


def test_loo_scores_are_exact_not_plug_in() -> None:
    """20 bounce + 1 break: the break row's LOO score must be computed with itself removed."""
    rows = _rows(["bounce"] * 20 + ["break"])
    rep = forecast(rows, symbol="BTCUSDT", key=KEY)
    k = KAPPA
    # With the single break removed from all three levels, p_{-i}(break) = κ-chain on 20 bounces.
    g = {y: (20 * (y == "bounce") + k / 3) / (20 + k) for y in OUTCOMES}
    s = {y: (20 * (y == "bounce") + k * g[y]) / (20 + k) for y in OUTCOMES}
    c = {y: (20 * (y == "bounce") + k * s[y]) / (20 + k) for y in OUTCOMES}
    break_score = 1.0 - c["break"]
    # ⌈22·0.8⌉ = 18 → the 18th smallest of 21 scores is a bounce score, not the break one.
    assert rep.q_hat is not None
    assert rep.q_hat < break_score
    assert rep.pred_set == frozenset({"bounce"})
    assert rep.decisive == "bounce"


def test_marginal_coverage_holds_on_exchangeable_data() -> None:
    """Simulated classes with p=(0.6, 0.3, 0.1): the true outcome lands in the set ≥ 80%."""
    rng = random.Random(11)
    hits = 0
    trials = 0
    for _ in range(200):
        history = [rng.choices(OUTCOMES, weights=(6, 3, 1))[0] for _ in range(40)]
        truth = rng.choices(OUTCOMES, weights=(6, 3, 1))[0]
        rep = forecast(_rows(history), symbol="BTCUSDT", key=KEY)
        trials += 1
        hits += truth in rep.pred_set
    assert hits / trials >= 0.8


def test_two_runs_same_report() -> None:
    rows = _rows(["bounce"] * 15 + ["break"] * 7 + ["die"] * 3)
    assert forecast(rows, symbol="BTCUSDT", key=KEY) == forecast(rows, symbol="BTCUSDT", key=KEY)


def test_sample_and_parameters_validate() -> None:
    with pytest.raises(ValueError):
        Sample(symbol="BTCUSDT", class_key=KEY, outcome="pending")
    with pytest.raises(ValueError):
        forecast([], symbol="BTCUSDT", key=KEY, kappa=0)
    with pytest.raises(ValueError):
        forecast([], symbol="BTCUSDT", key=KEY, alpha=1.0)

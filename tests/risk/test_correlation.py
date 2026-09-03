"""One idea per correlation group: static groups + rolling ρ; unknown ρ is not a block."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.risk.account import Account
from capitalizator.risk.config import RiskConfig
from capitalizator.risk.correlation import (
    MIN_ALIGNED_RETURNS,
    CorrelationGuard,
    CorrGroupsError,
    load_groups,
    pearson,
    returns_from_closes,
)


def test_repo_groups_load_and_are_disjoint() -> None:
    groups = load_groups()
    assert groups["BTCUSDT"] == groups["ETHUSDT"] == "majors"
    assert groups["ARBUSDT"] == groups["OPUSDT"] == "l2_eth"
    assert groups["SOLUSDT"] != groups["XRPUSDT"]


def test_duplicate_symbol_is_refused(tmp_path) -> None:
    p = tmp_path / "g.yaml"
    p.write_text("groups:\n  a: [X, Y]\n  b: [Y]\n", encoding="utf-8")
    with pytest.raises(CorrGroupsError, match="two groups"):
        load_groups(p)
    p.write_text("groups: {}\nextra: 1\n", encoding="utf-8")
    with pytest.raises(CorrGroupsError):
        load_groups(p)


def test_pearson_needs_aligned_samples_and_variance() -> None:
    xs = [Decimal(i) for i in range(MIN_ALIGNED_RETURNS)]
    assert abs(pearson(xs, xs) - Decimal(1)) < Decimal("1e-20")
    assert abs(pearson(xs, [-x for x in xs]) + Decimal(1)) < Decimal("1e-20")
    assert pearson(xs[:10], xs[:10]) is None  # too few
    assert pearson(xs, [Decimal(1)] * MIN_ALIGNED_RETURNS) is None  # flat


def test_guard_blocks_by_group_then_by_rho() -> None:
    guard = CorrelationGuard.load(threshold=Decimal("0.8"))
    assert guard.blocks("ETHUSDT", ["BTCUSDT"]) == (True, "corr:BTCUSDT:group:majors")
    assert guard.blocks("SOLUSDT", ["BTCUSDT"]) == (False, "ok")
    # dynamic: SOL and DOGE move together → blocked once ρ is refreshed
    closes_a = [(i, Decimal(100 + (i % 7))) for i in range(60)]
    closes_b = [(i, Decimal(50 + (i % 7) * 2)) for i in range(60)]
    n = guard.refresh({"SOLUSDT": returns_from_closes(closes_a),
                       "DOGEUSDT": returns_from_closes(closes_b), "XRPUSDT": {}})
    assert n == 1
    blocked, why = guard.blocks("DOGEUSDT", ["SOLUSDT"])
    assert blocked and why.startswith("corr:SOLUSDT:rho:")
    # opposite side is also one bet (a hedge is not a thesis): the rule has no side
    assert guard.blocks("SOLUSDT", ["DOGEUSDT"])[0] is True
    # unknown ρ (no aligned returns) is not a block
    assert guard.blocks("XRPUSDT", ["SOLUSDT"]) == (False, "ok")


def test_account_applies_the_guard_only_with_more_than_one_slot() -> None:
    one = Account(config=RiskConfig(max_open_positions=1))
    assert one.correlation is None
    three = Account(config=RiskConfig(max_open_positions=3))
    assert three.correlation is not None
    assert three.sizing_equity() == three.equity
    part = Account(config=RiskConfig(participating_share=Decimal("0.25")))
    assert part.sizing_equity() == part.equity * Decimal("0.25")


def test_budget_keys_per_window_and_daily_total() -> None:
    from datetime import UTC, datetime

    acct = Account(config=RiskConfig(max_intents_per_session=8))
    now = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    b = acct.budget(now, key="2026-01-05:europe", max_n=5)
    assert b.max_n == 5
    for _ in range(5):
        b.on_intent()
    assert b.allow_entry() is False
    c = acct.budget(now, key="2026-01-05:overlap", max_n=20)
    assert c.max_n == 8  # operator ceiling wins over a larger window budget
    c.on_intent()
    assert acct.daily_intents(now) == 6
    closed = acct.budget(now, key="2026-01-05:night", max_n=0)
    assert closed.allow_entry() is False
    with pytest.raises(ValueError):
        closed.on_intent()
    # a newer day drops yesterday's keys
    acct.budget(datetime(2026, 1, 6, 9, 0, tzinfo=UTC), key="2026-01-06:europe", max_n=5)
    assert all(k.startswith("2026-01-06") for k in acct._budgets)

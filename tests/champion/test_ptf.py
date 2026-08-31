"""PTF: ρ = E[R] × risk% / hours. Empty table is empty. No world rank."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.champion.ptf import ClassStat, PtfTable, rho


def _stat(*, n: int, avg_r: str = "0.5", hours: str = "3") -> ClassStat:
    return ClassStat(
        class_id="bounce × REJECT × DEFEND × BTC_box",
        n=n,
        avg_r=Decimal(avg_r),
        hours=Decimal(hours),
    )


def test_n_below_20_rho_unknown() -> None:
    row = PtfTable().evaluate(_stat(n=19))
    assert row.rho is None
    assert row.pickable is False
    assert PtfTable().pick([row]) is None


def test_n_20_formula() -> None:
    row = PtfTable().evaluate(_stat(n=20, avg_r="0.5", hours="3"))
    assert row.rho == rho(Decimal("0.5"), Decimal("0.01"), Decimal("3"))
    assert row.rho == Decimal("0.5") * Decimal("0.01") / Decimal("3")
    assert row.pickable is False


def test_n_138_not_pickable() -> None:
    row = PtfTable().evaluate(_stat(n=138))
    assert row.rho is not None
    assert row.pickable is False
    assert PtfTable().pick([row]) is None


def test_n_139_pickable() -> None:
    row = PtfTable().evaluate(_stat(n=139))
    assert row.pickable is True
    assert PtfTable().pick([row]) == row.class_id


def test_world_return_rank_is_none() -> None:
    assert PtfTable().world_return_rank() is None


def test_risk_above_f1_without_gate_raises() -> None:
    with pytest.raises(ValueError, match="inflate"):
        PtfTable().evaluate(_stat(n=20), risk_frac=Decimal("0.02"))


def test_post_gate_risk_without_flag_raises() -> None:
    with pytest.raises(ValueError, match="inflate"):
        PtfTable().evaluate(_stat(n=20), risk_frac=Decimal("0.012"))


def test_post_gate_risk_allowed_only_after_gate() -> None:
    row = PtfTable().evaluate(
        _stat(n=139),
        risk_frac=Decimal("0.012"),
        gate_passed=True,
    )
    assert row.rho == Decimal("0.5") * Decimal("0.012") / Decimal("3")


def test_hours_beyond_session_window_raises() -> None:
    with pytest.raises(ValueError, match="3h"):
        PtfTable().evaluate(_stat(n=20, hours="24"))


def test_empty_table_has_no_pick() -> None:
    assert PtfTable().pick([]) is None

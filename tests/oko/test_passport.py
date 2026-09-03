"""Passport: nothing normalised before 30 observations; median/MAD; roundtrip."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.oko.passport import MATURE_N, Passport, RobustStat


def test_immature_returns_none_not_zero() -> None:
    stat = RobustStat()
    for i in range(MATURE_N - 1):
        stat.add(Decimal(i))
    assert stat.mature is False
    assert stat.median() is None
    assert stat.mad() is None
    assert stat.z(Decimal("5")) is None
    assert stat.rel(Decimal("5")) is None


def test_median_mad_z_rel() -> None:
    stat = RobustStat(Decimal(v) for v in range(1, MATURE_N + 1))
    assert stat.mature is True
    assert stat.median() == Decimal("15.5")
    assert stat.mad() == Decimal("7.5")
    z = stat.z(Decimal("15.5") + Decimal("7.5") * Decimal("1.4826"))
    assert z is not None and abs(z - 1) < Decimal("1e-12")
    assert stat.rel(Decimal("31")) == Decimal("2")


def test_window_is_bounded() -> None:
    stat = RobustStat(window=MATURE_N)
    for i in range(100):
        stat.add(Decimal(i))
    assert stat.n == MATURE_N
    assert stat.median() == Decimal("84.5")


def test_rejects_non_decimal_and_non_finite() -> None:
    stat = RobustStat()
    with pytest.raises(TypeError):
        stat.add(1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        stat.add(Decimal("NaN"))


def test_passport_matures_on_all_five_stats() -> None:
    passport = Passport("BTCUSDT")
    for _ in range(MATURE_N):
        passport.observe(
            depth=Decimal("20"),
            spread_ticks=None,
            print_qtys=[Decimal("1")],
            prints_per_s=Decimal("0.5"),
            range_ticks=Decimal("2"),
        )
    assert passport.mature is False
    assert passport.spread_ticks.n == 0
    for _ in range(MATURE_N):
        passport.observe(
            depth=Decimal("20"),
            spread_ticks=Decimal("2"),
            print_qtys=[Decimal("1")],
            prints_per_s=Decimal("0.5"),
            range_ticks=Decimal("2"),
        )
    assert passport.mature is True
    assert passport.depth.median() == Decimal("20")


def test_passport_roundtrip_is_exact() -> None:
    passport = Passport("ETHUSDT")
    for i in range(MATURE_N):
        passport.observe(
            depth=Decimal(10 + i),
            spread_ticks=Decimal("1.5"),
            print_qtys=[Decimal("0.25"), Decimal("0.75")],
            prints_per_s=Decimal("0.125"),
            range_ticks=Decimal(i),
        )
    raw = passport.to_dict()
    back = Passport.from_dict(raw)
    assert back.symbol == "ETHUSDT"
    for name, stat in passport.stats().items():
        other = getattr(back, name)
        assert list(other.values) == list(stat.values)
    assert back.depth.median() == passport.depth.median()
    assert back.print_qty.n == MATURE_N * 2


def test_passport_rejects_negative_and_bad_payload() -> None:
    passport = Passport("BTCUSDT")
    with pytest.raises(ValueError):
        passport.observe(
            depth=Decimal("-1"),
            spread_ticks=None,
            print_qtys=[],
            prints_per_s=Decimal("0"),
            range_ticks=None,
        )
    with pytest.raises(ValueError):
        passport.observe(
            depth=Decimal("1"),
            spread_ticks=None,
            print_qtys=[Decimal("0")],
            prints_per_s=Decimal("0"),
            range_ticks=None,
        )
    with pytest.raises(ValueError):
        Passport.from_dict({"symbol": "X", "depth": "not-a-list"})
    with pytest.raises(ValueError):
        Passport.from_dict({"symbol": "X", "depth": ["abc"]})
    with pytest.raises(ValueError):
        Passport("")


def test_oi_and_funding_stats_do_not_gate_maturity() -> None:
    from tests.oko.conftest import mature_passport

    passport = mature_passport()
    assert passport.mature is True
    assert passport.oi_delta_frac.n == 0
    assert passport.oi_peak(Decimal("1")) is None
    assert passport.funding_top5(Decimal("0.0001")) is None
    for i in range(MATURE_N):
        passport.observe_oi(delta_frac=Decimal("0.001"), level=Decimal(1000 + i))
        passport.observe_funding(Decimal(i) / 10000)
    assert passport.oi_peak(Decimal("1029")) is True
    assert passport.oi_peak(Decimal("1028")) is False
    assert passport.funding_top5(Decimal("0.0029")) is True
    assert passport.funding_top5(Decimal("0.0027")) is False
    with pytest.raises(ValueError):
        passport.observe_oi(delta_frac=Decimal("0"), level=Decimal("0"))
    back = Passport.from_dict(passport.to_dict())
    assert back.oi_level.n == MATURE_N and back.funding.n == MATURE_N
    assert back.oi_peak(Decimal("1029")) is True

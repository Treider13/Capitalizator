"""Eyelid: four VETO laws, Accord-or-Silence inside ОКО, +1 caps, size only cuts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.oko.eyelid import OkoVerdict, blind_verdict, oko_opens_size, verdict
from capitalizator.oko.footprint import FootprintReport
from capitalizator.oko.forecast import OUTCOMES, ForecastReport
from capitalizator.oko.memory import Recognition
from capitalizator.oko.shadow import FINGERPRINT_LEN, ShadowReport
from capitalizator.oko.weather import WeatherReport

FP = tuple([0] * FINGERPRINT_LEN)


def shadow(
    *,
    label: str = "CLEAN",
    book_trust: float | None = 1.0,
    tape_trust: float | None = 1.0,
    cascade: bool = False,
    spoof_side: str | None = None,
    spoof_score: float = 0.0,
) -> ShadowReport:
    return ShadowReport(
        label=label,  # type: ignore[arg-type]
        spoof_side=spoof_side,  # type: ignore[arg-type]
        spoof_score=spoof_score,
        opp_spoof_score=0.0,
        layering_score=0.0,
        layered_levels=0,
        flicker_n=0,
        cascade=cascade,
        thin=label == "THIN",
        book_trust=book_trust,
        tape_trust=tape_trust,
        fingerprint=FP,
        evidence={},
    )


def footprint(label: str = "NONE", side: str | None = None) -> FootprintReport:
    from capitalizator.oko.footprint import FOOTPRINT_LABELS

    return FootprintReport(
        label=label,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        oi_delta_frac=None,
        oi_z=None,
        iceberg_ratio=None,
        iceberg_refills=0,
        taker_volume_rel=None,
        liq_rel=None,
        liq_dominant=None,
        fingerprint=(
            FOOTPRINT_LABELS.index(label),
            0 if side is None else (1 if side == "bid" else 2),
            3,
        ),
        evidence={},
    )


def weather(regime: str = "RANGE", cp_prob: float | None = 0.05) -> WeatherReport:
    return WeatherReport(
        regime=regime,  # type: ignore[arg-type]
        cp_prob=cp_prob,
        run_map=50,
        run_n=50,
        run_mean=0.0,
        run_sigma=0.002,
        long_sigma=0.002,
        vol_ratio=1.0,
        n_bars=100,
    )


def forecast(decisive: str | None = None, *, n: int = 25) -> ForecastReport:
    if decisive is None:
        p = {"bounce": 0.5, "break": 0.4, "die": 0.1}
        pred = frozenset({"bounce", "break"})
    else:
        other = [y for y in OUTCOMES if y != decisive]
        p = {decisive: 0.8, other[0]: 0.15, other[1]: 0.05}
        pred = frozenset({decisive})
    return ForecastReport(
        class_key="k",
        n_class=n,
        n_symbol=n,
        n_global=n,
        p=p,
        pred_set=pred,
        q_hat=0.3,
        decisive=decisive,
    )


def recognition(recognised: bool = False) -> Recognition:
    if recognised:
        return Recognition(n=24, traps=20, trap_rate=20 / 24, lower_bound=0.64, recognised=True)
    return Recognition(n=3, traps=1, trap_rate=1 / 3, lower_bound=0.06, recognised=False)


def _v(**kw) -> OkoVerdict:
    args = dict(
        idea="bounce",
        zone_side="support",
        shadow=shadow(),
        footprint=footprint(),
        weather=weather(),
        forecast=forecast(),
        recognition=recognition(),
        mirror_ok=True,
    )
    args.update(kw)
    return verdict(**args)


def test_cascade_is_veto_for_any_idea() -> None:
    for idea in ("bounce", "breakout", "failed_break"):
        v = _v(idea=idea, shadow=shadow(label="CASCADE", cascade=True, book_trust=0.0))
        assert v.voice == "VETO"
        assert v.size_mult == Decimal("0")
        assert "cascade" in v.reason


def test_low_book_trust_is_veto_with_the_side_named() -> None:
    v = _v(shadow=shadow(label="SPOOF", book_trust=0.0, spoof_side="zone", spoof_score=1.0))
    assert v.voice == "VETO"
    assert "spoof on zone side" in v.reason
    v2 = _v(shadow=shadow(label="LAYERING", book_trust=0.3))
    assert v2.voice == "VETO"
    ok = _v(shadow=shadow(label="THIN", book_trust=0.5))
    assert ok.voice != "VETO"


def test_recognised_trap_is_veto() -> None:
    v = _v(recognition=recognition(True), forecast=forecast("bounce"))
    assert v.voice == "VETO"
    assert "immune memory" in v.reason


def test_regime_break_is_veto_soft_break_cuts_size() -> None:
    v = _v(weather=weather("TRANSITION", 0.75), forecast=forecast("bounce"))
    assert v.voice == "VETO"
    soft = _v(weather=weather("TRANSITION", 0.55), forecast=forecast("bounce"))
    assert soft.voice == 0  # +1 capped: weather transition
    assert soft.size_mult == Decimal("0.5")
    assert "cp_prob" in soft.reason


def test_decisive_forecast_with_us_is_plus_one() -> None:
    v = _v(forecast=forecast("bounce"))
    assert v.voice == 1
    assert v.size_mult == Decimal("1")
    assert v.p_bounce == 0.8
    b = _v(idea="breakout", forecast=forecast("break"))
    assert b.voice == 1
    fb = _v(idea="failed_break", forecast=forecast("bounce"))
    assert fb.voice == 1


def test_decisive_forecast_against_is_minus_one_even_without_mirror() -> None:
    v = _v(forecast=forecast("break"), mirror_ok=False)
    assert v.voice == -1
    assert "against" in v.reason
    b = _v(idea="breakout", forecast=forecast("bounce"))
    assert b.voice == -1


def test_no_decisive_forecast_is_zero() -> None:
    v = _v()
    assert v.voice == 0
    assert v.reason == "no decisive forecast"
    assert v.pred_set == frozenset({"bounce", "break"})


def test_vol_expansion_vs_bounce_is_minus_one_and_splits_with_forecast() -> None:
    v = _v(weather=weather("VOL_EXPANSION"))
    assert v.voice == -1
    split = _v(weather=weather("VOL_EXPANSION"), forecast=forecast("bounce"))
    assert split.voice == 0
    assert "inner split" in split.reason
    breakout = _v(idea="breakout", weather=weather("VOL_EXPANSION"))
    assert breakout.voice == 0


def test_plus_one_caps() -> None:
    assert _v(forecast=forecast("bounce"), mirror_ok=False).voice == 0
    assert _v(forecast=forecast("bounce"), weather=weather("UNKNOWN", None)).voice == 0
    assert (
        _v(forecast=forecast("bounce"), shadow=shadow(label="UNKNOWN", book_trust=None)).voice == 0
    )
    low_tape = _v(forecast=forecast("bounce"), shadow=shadow(tape_trust=0.4))
    assert low_tape.voice == 0
    assert low_tape.size_mult == Decimal("0.5")
    no_tape = _v(forecast=forecast("bounce"), shadow=shadow(tape_trust=None))
    assert no_tape.voice == 1


def test_size_only_cuts_with_a_floor() -> None:
    v = _v(shadow=shadow(book_trust=0.7, tape_trust=0.7), weather=weather("RANGE", 0.55))
    assert v.size_mult == Decimal("0.25")
    assert v.size_mult >= Decimal("0.25")
    assert oko_opens_size(v) is False
    assert oko_opens_size() is False
    with pytest.raises(ValueError):
        OkoVerdict(
            voice=1,
            label="CLEAN",
            regime="RANGE",
            reason="",
            size_mult=Decimal("1.5"),
            book_trust=1.0,
            tape_trust=1.0,
            cp_prob=0.0,
            p_bounce=1.0,
            p_break=0.0,
            p_die=0.0,
            pred_set=frozenset({"bounce"}),
            n_class=20,
            fingerprint=FP,
        )
    with pytest.raises(ValueError):
        OkoVerdict(
            voice="VETO",
            label="CLEAN",
            regime="RANGE",
            reason="",
            size_mult=Decimal("1"),
            book_trust=1.0,
            tape_trust=1.0,
            cp_prob=0.0,
            p_bounce=1.0,
            p_break=0.0,
            p_die=0.0,
            pred_set=frozenset({"bounce"}),
            n_class=20,
            fingerprint=FP,
        )


def test_blind_verdict_is_zero_with_the_forecast_written() -> None:
    v = blind_verdict(weather=weather(), forecast=forecast("bounce"))
    assert v.voice == 0
    assert v.label == "UNKNOWN"
    assert v.fingerprint == ()
    assert v.p_bounce == 0.8
    assert v.size_mult == Decimal("1")
    assert v.set_text == "bounce"


def test_two_runs_same_verdict() -> None:
    assert _v(forecast=forecast("bounce")) == _v(forecast=forecast("bounce"))


def test_footprint_against_the_idea_is_minus_one_and_with_it_is_not_plus_one() -> None:
    """A whale building on the ask under our long bounce → −1. On the bid → still 0."""
    against = _v(footprint=footprint("ICEBERG", "ask"))
    assert against.voice == -1
    assert "footprint iceberg on ask vs idea" in against.reason
    assert against.footprint == "ICEBERG" and against.footprint_side == "ask"
    with_us = _v(footprint=footprint("ABSORB", "bid"))
    assert with_us.voice == 0  # never +1 by itself
    build = _v(footprint=footprint("BUILD_SHORT", "ask"))
    assert build.voice == -1
    # Breakout of support needs the ask builder: bid builder is against it.
    brk = _v(idea="breakout", footprint=footprint("BUILD_LONG", "bid"))
    assert brk.voice == -1
    brk_ok = _v(idea="breakout", footprint=footprint("BUILD_SHORT", "ask"))
    assert brk_ok.voice == 0
    # Resistance bounce (short) wants the ask side.
    res = _v(zone_side="resistance", footprint=footprint("ABSORB", "bid"))
    assert res.voice == -1


def test_sweep_and_unwind_do_not_vote() -> None:
    assert _v(footprint=footprint("SWEEP", "ask")).voice == 0
    assert _v(footprint=footprint("UNWIND", None)).voice == 0
    assert _v(footprint=footprint("SWEEP", "ask"), forecast=forecast("bounce")).voice == 1


def test_footprint_against_splits_with_forecast_for() -> None:
    v = _v(footprint=footprint("ICEBERG", "ask"), forecast=forecast("bounce"))
    assert v.voice == 0
    assert "inner split" in v.reason


def test_fragility_veto_only_for_new_longs_and_only_with_all_three_flags() -> None:
    thin = shadow(label="THIN", book_trust=0.5)
    v = _v(shadow=thin, oi_peak=True, funding_top5=True)
    assert v.voice == "VETO"
    assert "fragility" in v.reason
    assert _v(shadow=thin, oi_peak=True, funding_top5=None).voice != "VETO"
    assert _v(shadow=thin, oi_peak=False, funding_top5=True).voice != "VETO"
    assert _v(shadow=shadow(), oi_peak=True, funding_top5=True).voice != "VETO"
    # A short (resistance bounce) is not "a new long": 3.15.5 is written for longs only.
    short = _v(zone_side="resistance", shadow=thin, oi_peak=True, funding_top5=True)
    assert short.voice != "VETO"


def test_combined_fingerprint_is_thirteen() -> None:
    v = _v(footprint=footprint("ABSORB", "bid"))
    assert len(v.fingerprint) == 13
    assert v.fingerprint[10:] == (5, 1, 3)

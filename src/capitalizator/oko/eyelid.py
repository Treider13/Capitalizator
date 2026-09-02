"""Eyelid — closes the eye. Turns the layers into one jury Voice.

VETO (the eye shuts, the trade is dead whatever the other five say):
  CASCADE                      liquidation run through the zone
  book_trust < 0.35            fake wall / layering on the book we would lean on
  immune Memory recognised     ≥20 look-alike windows, Wilson LB of trap rate > 0.5
  cp_prob ≥ 0.7                the regime broke inside the last bars
  fragility (3.15.5)           OI peak ∧ funding top-5% ∧ thin book → no new long

Otherwise the inner opinions follow the jury's own law — Accord-or-Silence:
  Forecast decisive for the idea → +1, against → −1
  VOL_EXPANSION on a bounce idea → −1
  Footprint building against the idea (ABSORB / ICEBERG / BUILD_*) → −1
  disagreement inside ОКО → 0
The Footprint never gives +1 by itself: it widens the Forecast class key.
Caps: +1 is not allowed when Weather is UNKNOWN/TRANSITION, Shadow is UNKNOWN,
tape_trust < 0.5, or the Mirror has not passed. −1 is always allowed.
size_mult ≤ 1 always: ×0.5 per weak trust / transition, floor 0.25, 0 on VETO.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from capitalizator.jury.desk import Voice
from capitalizator.oko.footprint import FootprintReport, combined_fingerprint, needed_side
from capitalizator.oko.forecast import ForecastReport
from capitalizator.oko.memory import Recognition, needed_outcome
from capitalizator.oko.shadow import ShadowLabel, ShadowReport
from capitalizator.oko.weather import Regime, WeatherReport
from capitalizator.whales.fragility import forbid_new_long

TRUST_VETO = 0.35
CP_VETO = 0.7
CP_SOFT = 0.5
TAPE_CAP = 0.5
TRUST_SIZE_CUT = 0.8
HALF = Decimal("0.5")
SIZE_FLOOR = Decimal("0.25")
ONE = Decimal("1")
ZERO = Decimal("0")


@dataclass(frozen=True)
class OkoVerdict:
    voice: Voice
    label: ShadowLabel
    regime: Regime
    reason: str
    size_mult: Decimal
    book_trust: float | None
    tape_trust: float | None
    cp_prob: float | None
    p_bounce: float
    p_break: float
    p_die: float
    pred_set: frozenset[str]
    n_class: int
    fingerprint: tuple[int, ...]
    footprint: str = "NONE"
    footprint_side: str | None = None
    oi_z: float | None = None
    liq_rel: float | None = None

    def __post_init__(self) -> None:
        if self.voice not in (-1, 0, 1, "VETO"):
            raise ValueError(f"bad voice: {self.voice!r}")
        if self.size_mult < 0 or self.size_mult > ONE:
            raise ValueError("size_mult must be in [0, 1]")
        if self.voice == "VETO" and self.size_mult != ZERO:
            raise ValueError("VETO carries size 0")

    @property
    def voice_text(self) -> str:
        return str(self.voice)

    @property
    def set_text(self) -> str:
        return "|".join(sorted(self.pred_set))


def oko_opens_size(_verdict: OkoVerdict | None = None) -> bool:
    """ОКО cuts; it never opens. Same invariant as jury weights."""
    return False


def verdict(
    *,
    idea: str,
    zone_side: str,
    shadow: ShadowReport,
    footprint: FootprintReport,
    weather: WeatherReport,
    forecast: ForecastReport,
    recognition: Recognition,
    mirror_ok: bool,
    oi_peak: bool | None = None,
    funding_top5: bool | None = None,
) -> OkoVerdict:
    need = needed_outcome(idea)
    want_side = needed_side(idea=idea, zone_side=zone_side)
    idea_is_long = want_side == "bid"
    reasons: list[str] = []

    veto = _veto_reason(shadow, weather, recognition)
    if veto is None and idea_is_long:
        if forbid_new_long(oi_peak=oi_peak, funding_top5=funding_top5, thin_book=shadow.thin):
            veto = "fragility: oi peak, funding top-5%, thin book"
    if veto is not None:
        return _pack(
            voice="VETO",
            size=ZERO,
            reason=veto,
            shadow=shadow,
            footprint=footprint,
            weather=weather,
            forecast=forecast,
        )

    opinions: list[int] = []
    if forecast.decisive is not None:
        if forecast.decisive == need:
            opinions.append(1)
            reasons.append(f"forecast {forecast.decisive} n={forecast.n_class}")
        else:
            opinions.append(-1)
            reasons.append(f"forecast against: {forecast.decisive} n={forecast.n_class}")
    if weather.regime == "VOL_EXPANSION" and need == "bounce":
        opinions.append(-1)
        reasons.append("vol expansion vs bounce")
    if footprint.votes and footprint.side != want_side:
        opinions.append(-1)
        reasons.append(f"footprint {footprint.label.lower()} on {footprint.side} vs idea")

    voice: Voice
    if 1 in opinions and -1 in opinions:
        voice = 0
        reasons.append("inner split")
    elif -1 in opinions:
        voice = -1
    elif 1 in opinions:
        voice = 1
    else:
        voice = 0
        if not reasons:
            reasons.append("no decisive forecast")

    size = ONE
    if voice == 1:
        cap = _plus_cap(shadow, weather, mirror_ok)
        if cap is not None:
            voice = 0
            reasons.append(cap)
    if shadow.book_trust is not None and shadow.book_trust < TRUST_SIZE_CUT:
        size *= HALF
        reasons.append(f"book_trust {shadow.book_trust:.2f}")
    if shadow.tape_trust is not None and shadow.tape_trust < TRUST_SIZE_CUT:
        size *= HALF
        reasons.append(f"tape_trust {shadow.tape_trust:.2f}")
    if weather.cp_prob is not None and weather.cp_prob >= CP_SOFT:
        size *= HALF
        reasons.append(f"cp_prob {weather.cp_prob:.2f}")
    if size < SIZE_FLOOR:
        size = SIZE_FLOOR
    return _pack(
        voice=voice,
        size=size,
        reason="; ".join(reasons),
        shadow=shadow,
        footprint=footprint,
        weather=weather,
        forecast=forecast,
    )


def blind_verdict(*, weather: WeatherReport, forecast: ForecastReport) -> OkoVerdict:
    """No book at the print → ОКО saw nothing. Voice 0, size untouched, no fingerprint.

    The Forecast is still written to the journal; it is not allowed to vote
    without a Shadow, because a +1 on a book we never saw is exactly the trap.
    """
    return OkoVerdict(
        voice=0,
        label="UNKNOWN",
        regime=weather.regime,
        reason="no book at the print",
        size_mult=ONE,
        book_trust=None,
        tape_trust=None,
        cp_prob=weather.cp_prob,
        p_bounce=forecast.p["bounce"],
        p_break=forecast.p["break"],
        p_die=forecast.p["die"],
        pred_set=forecast.pred_set,
        n_class=forecast.n_class,
        fingerprint=(),
    )


def _veto_reason(
    shadow: ShadowReport, weather: WeatherReport, recognition: Recognition
) -> str | None:
    if shadow.cascade:
        return "cascade through the zone"
    if shadow.book_trust is not None and shadow.book_trust < TRUST_VETO:
        side = shadow.spoof_side or "book"
        return f"{shadow.label.lower()} on {side} side, book_trust {shadow.book_trust:.2f}"
    if recognition.recognised:
        assert recognition.lower_bound is not None
        return (
            f"immune memory: trap {recognition.traps}/{recognition.n}, "
            f"lb {recognition.lower_bound:.2f}"
        )
    if weather.cp_prob is not None and weather.cp_prob >= CP_VETO:
        return f"regime break, cp_prob {weather.cp_prob:.2f}"
    return None


def _plus_cap(shadow: ShadowReport, weather: WeatherReport, mirror_ok: bool) -> str | None:
    if not mirror_ok:
        return "mirror not passed"
    if weather.regime in {"UNKNOWN", "TRANSITION"}:
        return f"weather {weather.regime.lower()}"
    if shadow.label == "UNKNOWN":
        return "no book in window"
    if shadow.tape_trust is not None and shadow.tape_trust < TAPE_CAP:
        return f"tape_trust {shadow.tape_trust:.2f}"
    return None


def _pack(
    *,
    voice: Voice,
    size: Decimal,
    reason: str,
    shadow: ShadowReport,
    footprint: FootprintReport,
    weather: WeatherReport,
    forecast: ForecastReport,
) -> OkoVerdict:
    return OkoVerdict(
        voice=voice,
        label=shadow.label,
        regime=weather.regime,
        reason=reason,
        size_mult=size,
        book_trust=shadow.book_trust,
        tape_trust=shadow.tape_trust,
        cp_prob=weather.cp_prob,
        p_bounce=forecast.p["bounce"],
        p_break=forecast.p["break"],
        p_die=forecast.p["die"],
        pred_set=forecast.pred_set,
        n_class=forecast.n_class,
        fingerprint=combined_fingerprint(shadow.fingerprint, footprint),
        footprint=footprint.label,
        footprint_side=footprint.side,
        oi_z=None if footprint.oi_z is None else float(footprint.oi_z),
        liq_rel=None if footprint.liq_rel is None else float(footprint.liq_rel),
    )

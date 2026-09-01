"""WJD — five voices, Accord-or-Silence. Not an ensemble average.

INVENTION-JURY / PHASE-BUILD glossary:
any VETO → VETO; CAV and ZLG both 0 → SILENCE; opposite signs → SPLIT;
only +1 and 0 with at least one +1 → ACCORD.
Does not open size. Weights do not open size. F1 bounce idea only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Voice = Literal[-1, 0, 1, "VETO"]
JuryLabel = Literal["ACCORD", "SPLIT", "VETO", "SILENCE"]
CAV_LABELS = frozenset({"REJECT", "THROUGH", "COMPRESS", "DRIFT", "NOISE"})
ZLG_LABELS = frozenset({"DEFEND", "RETREAT", "IMPROVE", "FADE", "SILENCE"})
N_MIN = 20


@dataclass(frozen=True)
class Voices:
    cav: Voice
    zlg: Voice
    tape: Voice
    btc: Voice
    card: Voice


def decide(voices: Voices, *, risk_ok: bool = True) -> JuryLabel:
    """Accord-or-Silence. Disagreeing signs are never averaged."""
    if not risk_ok:
        return "VETO"
    votes = (voices.cav, voices.zlg, voices.tape, voices.btc, voices.card)
    if any(v == "VETO" for v in votes):
        return "VETO"
    if voices.cav == 0 and voices.zlg == 0:
        return "SILENCE"
    if voices.cav in (1, -1) and voices.zlg in (1, -1) and voices.cav != voices.zlg:
        return "SPLIT"
    signed = [v for v in votes if v in (1, -1)]
    if 1 in signed and -1 in signed:
        return "SPLIT"
    if 1 in signed and -1 not in signed:
        return "ACCORD"
    return "SILENCE"


def voices_for_breakout(
    *,
    cav: str | None,
    n_cav: int,
    zlg: str | None,
    n_zlg: int,
    tape_eaten: bool | None,
    btc_regime: str | None,
    card_bearing_verdict: str | None = None,
    trades_in_window: int | None = None,
    wall_no_print: bool = False,
    btc_break_against: bool = False,
    cpi_window: bool = False,
    btc_same_side: bool = False,
) -> Voices:
    """Breakout idea: THROUGH + eaten + RETREAT with us. First-minute is desk-side."""
    if n_cav < 0 or n_zlg < 0:
        raise ValueError("n must be >= 0")
    if cav is not None and cav not in CAV_LABELS:
        raise ValueError(f"unknown cav: {cav!r}")
    if zlg is not None and zlg not in ZLG_LABELS:
        raise ValueError(f"unknown zlg: {zlg!r}")
    return Voices(
        cav=_cav_breakout(cav, n_cav),
        zlg=_zlg_breakout(zlg, n_zlg),
        tape=_tape_breakout(tape_eaten, trades_in_window, wall_no_print),
        btc=_btc_bounce(btc_regime, btc_break_against, btc_same_side),
        card=_card_voice(card_bearing_verdict, cpi_window),
    )


def voices_for_failed_break(
    *,
    cav: str | None,
    n_cav: int,
    zlg: str | None,
    n_zlg: int,
    tape_eaten: bool | None,
    btc_regime: str | None,
    card_bearing_verdict: str | None = None,
    trades_in_window: int | None = None,
    wall_no_print: bool = False,
    btc_break_against: bool = False,
    cpi_window: bool = False,
    btc_same_side: bool = False,
) -> Voices:
    """Failed break → opposite bounce. New card_id is a desk concern."""
    return voices_for_bounce(
        cav=cav,
        n_cav=n_cav,
        zlg=zlg,
        n_zlg=n_zlg,
        tape_eaten=tape_eaten,
        btc_regime=btc_regime,
        card_bearing_verdict=card_bearing_verdict,
        trades_in_window=trades_in_window,
        wall_no_print=wall_no_print,
        btc_break_against=btc_break_against,
        cpi_window=cpi_window,
        btc_same_side=btc_same_side,
    )


def voices_for_bounce(
    *,
    cav: str | None,
    n_cav: int,
    zlg: str | None,
    n_zlg: int,
    tape_eaten: bool | None,
    btc_regime: str | None,
    card_bearing_verdict: str | None = None,
    trades_in_window: int | None = None,
    wall_no_print: bool = False,
    btc_break_against: bool = False,
    cpi_window: bool = False,
    btc_same_side: bool = False,
) -> Voices:
    """Map journal labels onto bounce-idea voices. Breakout mapping is not here."""
    if n_cav < 0 or n_zlg < 0:
        raise ValueError("n must be >= 0")
    if cav is not None and cav not in CAV_LABELS:
        raise ValueError(f"unknown cav: {cav!r}")
    if zlg is not None and zlg not in ZLG_LABELS:
        raise ValueError(f"unknown zlg: {zlg!r}")
    return Voices(
        cav=_cav_bounce(cav, n_cav),
        zlg=_zlg_bounce(zlg, n_zlg),
        tape=_tape_bounce(tape_eaten, trades_in_window, wall_no_print),
        btc=_btc_bounce(btc_regime, btc_break_against, btc_same_side),
        card=_card_voice(card_bearing_verdict, cpi_window),
    )


def rho_class_id(*, setup: str, cav: str, zlg: str, btc: str) -> str:
    """INVENTION-JURY example: bounce × REJECT × DEFEND × BTC_box."""
    if not setup or not cav or not zlg or not btc:
        raise ValueError("class_id parts must be non-empty")
    return f"{setup} × {cav} × {zlg} × BTC_{btc}"


def _cav_bounce(cav: str | None, n: int) -> Voice:
    if cav is None:
        return 0
    if cav in {"DRIFT", "COMPRESS"} or n < N_MIN:
        return 0
    if cav == "REJECT":
        return 1
    if cav == "THROUGH":
        return -1
    return 0


def _zlg_bounce(zlg: str | None, n: int) -> Voice:
    if zlg == "SILENCE":
        return "VETO"
    if zlg is None or n < N_MIN:
        return 0
    if zlg in {"DEFEND", "IMPROVE"}:
        return 1
    if zlg == "RETREAT":
        return -1
    return 0


def _tape_bounce(
    tape_eaten: bool | None,
    trades_in_window: int | None,
    wall_no_print: bool,
) -> Voice:
    if wall_no_print:
        return "VETO"
    if trades_in_window is not None and trades_in_window <= 0:
        return 0
    if tape_eaten is None:
        return 0
    return -1 if tape_eaten else 1


def _cav_breakout(cav: str | None, n: int) -> Voice:
    if cav is None:
        return 0
    if cav in {"DRIFT", "COMPRESS"} or n < N_MIN:
        return 0
    if cav == "THROUGH":
        return 1
    if cav == "REJECT":
        return -1
    return 0


def _zlg_breakout(zlg: str | None, n: int) -> Voice:
    if zlg == "SILENCE":
        return "VETO"
    if zlg is None or n < N_MIN:
        return 0
    if zlg == "RETREAT":
        return 1
    if zlg in {"DEFEND", "IMPROVE"}:
        return -1
    return 0


def _tape_breakout(
    tape_eaten: bool | None,
    trades_in_window: int | None,
    wall_no_print: bool,
) -> Voice:
    if wall_no_print:
        return "VETO"
    if trades_in_window is not None and trades_in_window <= 0:
        return 0
    if tape_eaten is None:
        return 0
    return 1 if tape_eaten else -1


def _btc_bounce(regime: str | None, break_against: bool, same_side: bool = False) -> Voice:
    """+1 = box or same side as the alt idea. Wick/break-against is VETO."""
    if break_against:
        return "VETO"
    if regime == "box" or same_side:
        return 1
    return 0


def _card_voice(verdict: str | None, cpi_window: bool) -> Voice:
    if cpi_window:
        return "VETO"
    if verdict in {"REFUTED", "UNVERIFIABLE"}:
        return "VETO"
    if verdict == "VERIFIED":
        return 1
    return 0

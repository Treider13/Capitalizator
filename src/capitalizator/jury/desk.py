"""WJD — six voices, Accord-or-Silence. Not an ensemble average.

Two kinds of voice (audit 2026-09-03, jury §3.1):

  facts    cav (closed working bar), zlg (book gesture in the 8 s window),
           oko (the eye's window read), tape for a *breakout* (the level was
           eaten) — may say +1 / −1 / VETO.
  filters  tape for a bounce, btc, card — may say VETO / −1 / 0, never +1.
           "The wall was not eaten", "BTC is in a box", "the card proposes" are
           the *absence* of a bad sign, not evidence for the trade. Before this
           rule CAV=REJECT alone plus three such non-events made ACCORD — an entry
           on chart geometry with no first fact from the book.

Decision:
  any VETO                          → VETO
  cav == 0 and zlg == 0             → SILENCE
  a +1 and a −1 among the voices    → SPLIT
  a book fact == +1 and no −1       → ACCORD   (book fact: zlg, oko, or tape on a breakout;
                                                the chart may be 0 — a plain bounce is DRIFT)
  otherwise                         → SILENCE  (chart alone never enters; the shadow learns)

Does not open size. Weights do not open size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Voice = Literal[-1, 0, 1, "VETO"]
VOICES = (-1, 0, 1, "VETO")
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
    oko: Voice = 0

    def __post_init__(self) -> None:
        for name in ("cav", "zlg", "tape", "btc", "card", "oko"):
            if getattr(self, name) not in VOICES:
                raise ValueError(f"{name} voice must be -1|0|1|VETO")


def oko_voice(value: object) -> Voice:
    """Registry / journal form → Voice. None and unknown text are 0 (ОКО silent)."""
    if value is None:
        return 0
    if value == "VETO":
        return "VETO"
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value in (-1, 0, 1):
        return value  # type: ignore[return-value]
    if isinstance(value, str):
        try:
            number = int(value)
        except ValueError:
            return 0
        if number in (-1, 0, 1):
            return number  # type: ignore[return-value]
    return 0


BOOK_FACTS = ("zlg", "oko", "tape")


def decide(voices: Voices, *, risk_ok: bool = True) -> JuryLabel:
    """Accord-or-Silence. Disagreeing signs are never averaged; a bare chart never enters."""
    if not risk_ok:
        return "VETO"
    votes = (voices.cav, voices.zlg, voices.tape, voices.btc, voices.card, voices.oko)
    if any(v == "VETO" for v in votes):
        return "VETO"
    if voices.cav == 0 and voices.zlg == 0:
        return "SILENCE"
    signed = [v for v in votes if v in (1, -1)]
    if 1 in signed and -1 in signed:
        return "SPLIT"
    if -1 in signed:
        return "SPLIT"
    book_plus = any(getattr(voices, name) == 1 for name in BOOK_FACTS)
    if book_plus:
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
    oko: Voice = 0,
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
        oko=oko,
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
    oko: Voice = 0,
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
        oko=oko,
    )


def voices_for_spring(
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
    oko: Voice = 0,
) -> Voices:
    """Spring = wick through the zone, close back inside, traded WITH the zone.

    Same voice table as bounce on purpose: REJECT (+1) is literally this bar,
    DEFEND (+1) is the book refilling the level. The old `failed_break` path
    used these bullish voices to ACCORD a *short* — that inversion is gone.
    """
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
        oko=oko,
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
    oko: Voice = 0,
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
        oko=oko,
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
    """Filter for a bounce: eaten level → −1, wall without a print → VETO. A level
    that was *not* eaten is the absence of a bad sign (0), not a vote for the trade."""
    if wall_no_print:
        return "VETO"
    if trades_in_window is not None and trades_in_window <= 0:
        return 0
    if tape_eaten is None:
        return 0
    return -1 if tape_eaten else 0


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
    """Filter: BTC breaking its own zone against the alt idea is VETO. A box or the
    same side is permission, not evidence — 0."""
    if break_against:
        return "VETO"
    return 0


def _card_voice(verdict: str | None, cpi_window: bool) -> Voice:
    """Filter: a refuted / unverifiable bearing claim or a macro window is VETO. A
    card that proposes is context, not a fact from the book — 0."""
    if cpi_window:
        return "VETO"
    if verdict in {"REFUTED", "UNVERIFIABLE", "veto"}:
        return "VETO"
    return 0

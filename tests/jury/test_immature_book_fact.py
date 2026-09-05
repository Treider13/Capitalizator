"""A printed book gesture is a ticket even before n_min. Chart still needs n.

SILENCE stays VETO. Missing gesture stays 0. Chart alone stays SILENCE.
"""

from __future__ import annotations

from capitalizator.jury.desk import Voices, decide, voices_for_bounce, voices_for_breakout


def test_immature_defend_is_book_plus_accord() -> None:
    voices = voices_for_bounce(
        cav="DRIFT",
        n_cav=5,
        zlg="DEFEND",
        n_zlg=8,
        tape_eaten=False,
        btc_regime="box",
    )
    assert voices.cav == 0
    assert voices.zlg == 1
    assert decide(voices) == "ACCORD"


def test_immature_improve_is_book_plus() -> None:
    voices = voices_for_bounce(
        cav=None,
        n_cav=0,
        zlg="IMPROVE",
        n_zlg=3,
        tape_eaten=False,
        btc_regime="box",
    )
    assert voices.zlg == 1
    assert decide(voices) == "ACCORD"


def test_chart_reject_without_gesture_stays_silence() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg=None,
        n_zlg=5,
        tape_eaten=False,
        btc_regime="box",
        card_bearing_verdict="propose",
    )
    assert voices.cav == 1
    assert voices.zlg == 0
    assert decide(voices) == "SILENCE"


def test_silence_gesture_still_veto_when_n_thin() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="SILENCE",
        n_zlg=4,
        tape_eaten=False,
        btc_regime="box",
    )
    assert voices.zlg == "VETO"
    assert decide(voices) == "VETO"


def test_immature_retreat_is_breakout_book_plus() -> None:
    voices = voices_for_breakout(
        cav="THROUGH",
        n_cav=20,
        zlg="RETREAT",
        n_zlg=7,
        tape_eaten=True,
        btc_regime="box",
        btc_same_side=True,
    )
    assert voices.zlg == 1
    assert decide(voices) == "ACCORD"


def test_bare_chart_voices_still_silence() -> None:
    assert decide(Voices(cav=1, zlg=0, tape=0, btc=0, card=0, oko=0)) == "SILENCE"

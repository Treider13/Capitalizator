"""WJD: disagreeing CAV/ZLG is SPLIT, not an average. No size."""

from __future__ import annotations

from capitalizator.jury.desk import Voices, decide, rho_class_id, voices_for_bounce


def test_veto_wins() -> None:
    voices = Voices(cav=1, zlg=1, tape=1, btc=1, card="VETO")
    assert decide(voices) == "VETO"


def test_cav_zlg_mute_is_silence() -> None:
    voices = Voices(cav=0, zlg=0, tape=1, btc=1, card=1)
    assert decide(voices) == "SILENCE"


def test_cav_zlg_opposite_is_split() -> None:
    voices = Voices(cav=1, zlg=-1, tape=1, btc=1, card=1)
    assert decide(voices) == "SPLIT"
    assert decide(voices) != "ACCORD"


def test_mixed_other_channel_is_split() -> None:
    voices = Voices(cav=1, zlg=1, tape=-1, btc=1, card=1)
    assert decide(voices) == "SPLIT"


def test_plus_and_zero_is_accord() -> None:
    voices = Voices(cav=1, zlg=1, tape=0, btc=1, card=0)
    assert decide(voices) == "ACCORD"


def test_risk_unsigned_is_veto() -> None:
    voices = Voices(cav=1, zlg=1, tape=1, btc=1, card=1)
    assert decide(voices, risk_ok=False) == "VETO"


def test_two_runs_same_label() -> None:
    voices = Voices(cav=1, zlg=-1, tape=1, btc=0, card=0)
    assert decide(voices) == decide(voices) == "SPLIT"


def test_reject_defend_n20_is_accord_candidate() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        card_bearing_verdict="VERIFIED",
    )
    assert voices.cav == 1
    assert voices.zlg == 1
    assert decide(voices) == "ACCORD"


def test_through_defend_is_split() -> None:
    voices = voices_for_bounce(
        cav="THROUGH",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
    )
    assert voices.cav == -1
    assert voices.zlg == 1
    assert decide(voices) == "SPLIT"


def test_n_below_20_does_not_give_signed_cav_zlg() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=19,
        zlg="DEFEND",
        n_zlg=19,
        tape_eaten=False,
        btc_regime="box",
    )
    assert voices.cav == 0
    assert voices.zlg == 0
    assert decide(voices) == "SILENCE"


def test_silence_gesture_is_veto() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="SILENCE",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
    )
    assert voices.zlg == "VETO"
    assert decide(voices) == "VETO"


def test_btc_trend_is_not_a_break_veto() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="trend",
    )
    assert voices.btc == 0


def test_btc_same_side_is_plus_one() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="long",
        btc_same_side=True,
    )
    assert voices.btc == 1


def test_btc_break_against_is_veto() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        btc_break_against=True,
    )
    assert decide(voices) == "VETO"


def test_class_id_matches_spec_example() -> None:
    assert rho_class_id(
        setup="bounce",
        cav="REJECT",
        zlg="DEFEND",
        btc="box",
    ) == "bounce × REJECT × DEFEND × BTC_box"

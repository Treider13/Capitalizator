"""WJD: disagreeing CAV/ZLG is SPLIT, not an average. No size."""

from __future__ import annotations

from capitalizator.jury.desk import (
    Voices,
    decide,
    oko_voice,
    rho_class_id,
    voices_for_bounce,
    voices_for_breakout,
    voices_for_failed_break,
)


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


def test_btc_same_side_is_permission_not_evidence() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="long",
        btc_same_side=True,
    )
    assert voices.btc == 0  # filters never say +1


def test_chart_alone_plus_non_events_is_silence_not_accord() -> None:
    """The bare-chart entry: REJECT with n≥20, ZLG still learning (n<20), wall not eaten,
    BTC in a box, card proposes. Before: ACCORD. Now: SILENCE — no first fact from the book."""
    voices = voices_for_bounce(
        cav="REJECT", n_cav=20, zlg="DEFEND", n_zlg=5, tape_eaten=False,
        btc_regime="box", card_bearing_verdict="propose",
    )
    assert voices.tape == 0 and voices.btc == 0 and voices.card == 0
    assert voices.cav == 1 and voices.zlg == 0
    assert decide(voices) == "SILENCE"
    # the same touch with the book fact mature → ACCORD
    mature = voices_for_bounce(
        cav="REJECT", n_cav=20, zlg="DEFEND", n_zlg=20, tape_eaten=False,
        btc_regime="box", card_bearing_verdict="propose",
    )
    assert decide(mature) == "ACCORD"
    # or with the eye as the book fact
    assert decide(Voices(cav=1, zlg=0, tape=0, btc=0, card=0, oko=1)) == "ACCORD"
    # book facts with a neutral chart (a plain bounce is DRIFT = 0) do enter: the book
    # is the first fact, the chart is confirmation
    assert decide(Voices(cav=0, zlg=1, tape=0, btc=0, card=0, oko=1)) == "ACCORD"
    # a bare chart with a neutral book never enters
    assert decide(Voices(cav=1, zlg=0, tape=0, btc=0, card=0, oko=0)) == "SILENCE"
    # an eaten level is a real −1 against a bounce
    eaten = voices_for_bounce(
        cav="REJECT", n_cav=20, zlg="DEFEND", n_zlg=20, tape_eaten=True, btc_regime="box",
    )
    assert eaten.tape == -1 and decide(eaten) == "SPLIT"


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


def test_oko_defaults_to_absent_zero() -> None:
    """Five-voice callers keep their label: ОКО absent is 0, not a vote."""
    voices = Voices(cav=1, zlg=1, tape=1, btc=1, card=1)
    assert voices.oko == 0
    assert decide(voices) == "ACCORD"


def test_oko_veto_kills_a_full_accord() -> None:
    voices = Voices(cav=1, zlg=1, tape=1, btc=1, card=1, oko="VETO")
    assert decide(voices) == "VETO"


def test_oko_minus_one_splits() -> None:
    voices = Voices(cav=1, zlg=1, tape=1, btc=1, card=1, oko=-1)
    assert decide(voices) == "SPLIT"


def test_oko_plus_one_does_not_open_accord_alone() -> None:
    """CAV and ZLG both mute is still SILENCE. The eye confirms, it does not lead."""
    voices = Voices(cav=0, zlg=0, tape=0, btc=0, card=0, oko=1)
    assert decide(voices) == "SILENCE"
    with_chart = Voices(cav=1, zlg=1, tape=0, btc=0, card=0, oko=1)
    assert decide(with_chart) == "ACCORD"


def test_oko_voice_rejects_unknown_values() -> None:
    import pytest

    with pytest.raises(ValueError, match="oko"):
        Voices(cav=1, zlg=1, tape=1, btc=1, card=1, oko=2)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cav"):
        Voices(cav="yes", zlg=1, tape=1, btc=1, card=1)  # type: ignore[arg-type]


def test_voices_for_bounce_carries_oko() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        oko="VETO",
    )
    assert voices.oko == "VETO"
    assert decide(voices) == "VETO"
    against = voices_for_breakout(
        cav="THROUGH",
        n_cav=20,
        zlg="RETREAT",
        n_zlg=20,
        tape_eaten=True,
        btc_regime="box",
        oko=-1,
    )
    assert decide(against) == "SPLIT"
    failed = voices_for_failed_break(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        oko=1,
    )
    assert failed.oko == 1


def test_oko_voice_parser_from_registry_forms() -> None:
    assert oko_voice(None) == 0
    assert oko_voice("VETO") == "VETO"
    assert oko_voice(-1) == -1
    assert oko_voice("1") == 1
    assert oko_voice("-1") == -1
    assert oko_voice("0") == 0
    assert oko_voice("maybe") == 0
    assert oko_voice(True) == 0
    assert oko_voice(2) == 0


def test_class_id_matches_spec_example() -> None:
    assert rho_class_id(
        setup="bounce",
        cav="REJECT",
        zlg="DEFEND",
        btc="box",
    ) == "bounce × REJECT × DEFEND × BTC_box"


def test_voices_for_spring_carries_oko() -> None:
    from capitalizator.jury.desk import voices_for_spring

    voices = voices_for_spring(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        oko="VETO",
    )
    assert voices.oko == "VETO"
    assert decide(voices) == "VETO"

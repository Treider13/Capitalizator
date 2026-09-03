"""ОКО in propose: VETO → None; −1 splits the jury; size_mult only cuts; never > 1."""

from __future__ import annotations

from decimal import Decimal

import pytest
from tests.exec.test_bounce_gates import _snap, _strategy

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine


def _jury_strategy() -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )


def _accord(**overrides: object) -> BounceSnapshot:
    raw: dict[str, object] = {
        "idea": "bounce",
        "jury": "ACCORD",
        "cav_label": "REJECT",
        "zlg_label": "DEFEND",
        "n_cav": 20,
        "n_zlg": 20,
        "gesture_n": 20,
        "tape_eaten": False,
        "btc_regime": "box",
        "btc_same_side": True,
        "card_bearing_verdict": "VERIFIED",
    }
    raw.update(overrides)
    return _snap(**raw)


def test_default_snapshot_has_no_eye() -> None:
    snap = _snap()
    assert snap.oko_voice == 0
    assert snap.oko_size_mult == Decimal("1")
    assert isinstance(_strategy().propose(snap), Intent)


def test_oko_veto_returns_none_even_without_jury() -> None:
    assert _strategy().propose(_snap(oko_voice="VETO")) is None
    assert _jury_strategy().propose(_accord(oko_voice="VETO")) is None


def test_oko_minus_one_splits_the_accord() -> None:
    assert isinstance(_jury_strategy().propose(_accord()), Intent)
    assert _jury_strategy().propose(_accord(oko_voice=-1)) is None


def test_oko_plus_one_keeps_accord_and_full_size() -> None:
    got = _jury_strategy().propose(_accord(oko_voice=1))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("1")


def test_oko_size_mult_only_cuts() -> None:
    got = _strategy().propose(_snap(oko_size_mult=Decimal("0.5")))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("0.5")
    # B cut_size already at 0.5: the smaller of the two wins, never the product.
    both = _strategy().propose(_snap(b_verdict="cut_size", oko_size_mult=Decimal("0.75")))
    assert isinstance(both, Intent)
    assert both.size_mult == Decimal("0.5")
    quarter = _strategy().propose(_snap(b_verdict="cut_size", oko_size_mult=Decimal("0.25")))
    assert isinstance(quarter, Intent)
    assert quarter.size_mult == Decimal("0.25")


def test_snapshot_rejects_size_above_one_and_bad_voice() -> None:
    with pytest.raises(ValueError, match="never opens size"):
        _snap(oko_size_mult=Decimal("1.5"))
    with pytest.raises(ValueError, match="oko_voice"):
        _snap(oko_voice=2)

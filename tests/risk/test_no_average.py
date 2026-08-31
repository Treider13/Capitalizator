"""−1.3: averaging cannot be a valid risk action."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from capitalizator.risk.schema import (
    FORBIDDEN_ACTIONS,
    Intent,
    ManageIntent,
    RiskEngine,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "anti" / "old_user_average.json"


def test_forbidden_words_not_in_enums() -> None:
    for word in FORBIDDEN_ACTIONS:
        assert word not in Intent.model_fields
        assert word not in ManageIntent.model_fields


def test_old_user_scheme_rejected() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    engine = RiskEngine()
    with pytest.raises((ValueError, ValidationError)):
        engine.validate(raw)


def test_each_forbidden_action_rejected() -> None:
    engine = RiskEngine()
    base = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "entry": "100",
        "stop": "99",
        "tp": "102",
        "tag": "unit",
    }
    for name in ("average_in", "add_to_position", "pyramid", "martingale"):
        raw = dict(base)
        raw[name] = True
        with pytest.raises((ValueError, ValidationError)):
            engine.validate(raw)


def test_clean_intent_accepted() -> None:
    intent = RiskEngine().validate(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "entry": "100",
            "stop": "99",
            "tp": "102",
            "tag": "bounce",
        }
    )
    assert intent.entry == Decimal("100")
    assert intent.tag == "bounce"


def test_manage_has_no_add() -> None:
    with pytest.raises(ValidationError):
        ManageIntent.model_validate({"action": "average_in"})
    ok = ManageIntent.model_validate({"action": "reduce", "fraction": "0.5"})
    assert ok.action == "reduce"

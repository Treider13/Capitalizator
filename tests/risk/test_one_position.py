"""Second intent while RiskEngine._open_position is set → reject."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Position, RiskEngine

INTENT = {
    "symbol": "BTCUSDT",
    "side": "buy",
    "entry": "100",
    "stop": "99",
    "tp": "102",
    "tag": "bounce",
}


def test_second_entry_rejected() -> None:
    engine = RiskEngine()
    assert engine.allow_entry() is True
    engine.on_open(INTENT)
    assert engine._open_position is not None
    assert engine.allow_entry() is False
    with pytest.raises(ValueError, match="already"):
        engine.on_open(INTENT)


def test_flat_allows_again() -> None:
    engine = RiskEngine()
    opened = engine.on_open(INTENT)
    assert isinstance(opened, Position)
    engine.on_flat()
    assert engine._open_position is None
    assert engine.allow_entry() is True


def test_flat_still_works_when_halts_tripped() -> None:
    """1.5.2: halt blocks a new entry. Flatten is RiskEngine, not Halts."""
    engine = RiskEngine()
    engine.on_open(INTENT)
    h = Halts(start_equity=Decimal("100000"))
    h.mark_liq()
    assert h.allow_entry() is False
    engine.on_flat()
    assert engine._open_position is None

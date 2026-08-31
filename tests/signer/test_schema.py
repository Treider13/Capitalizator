"""Signer.validate: testnet + week0 symbol + stop. No key. No send."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.signer.validate import Signer, UnsignedIntent


def _intent(**overrides: object) -> UnsignedIntent:
    raw: dict[str, object] = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "qty": Decimal("0.001"),
        "limit_px": Decimal("60000"),
        "stop_px": Decimal("59400"),
        "trading_mode": "testnet",
    }
    raw.update(overrides)
    return UnsignedIntent.model_validate(raw)


def test_valid_testnet_limit_and_stop() -> None:
    order = Signer().validate(_intent())
    assert order.trading_mode == "testnet"
    assert order.symbol == "BTCUSDT"
    assert order.stop_px < order.limit_px


def test_mainnet_mode_rejected() -> None:
    with pytest.raises(Exception, match="testnet|literal"):
        _intent(trading_mode="mainnet")


def test_symbol_outside_week0_rejected() -> None:
    with pytest.raises(ValueError, match="universe"):
        Signer().validate(_intent(symbol="SOLUSDT"))


def test_buy_stop_above_limit_rejected() -> None:
    with pytest.raises(ValueError, match="stop"):
        Signer().validate(_intent(stop_px=Decimal("61000")))


def test_signer_source_does_not_read_keys() -> None:
    from pathlib import Path

    from capitalizator.recorder.scan_keys import scan_tree

    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "signer"
    assert scan_tree(src) == []

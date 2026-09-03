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


def test_valid_demo_trading_venue() -> None:
    order = Signer().validate(_intent(trading_mode="demo"))
    assert order.trading_mode == "demo"


@pytest.mark.parametrize("mode", ["mainnet", "live", "paper", ""])
def test_unknown_venues_rejected(mode: str) -> None:
    with pytest.raises(Exception, match="venue|literal"):
        Signer().validate(_intent(trading_mode=mode))


@pytest.mark.parametrize("mode", ["live_sub", "live_main"])
def test_live_venues_are_stamped_as_themselves(mode: str) -> None:
    """A live order used to be stamped `demo` because the validator knew only paper
    venues: the journal then called a live fill a demo one. The gate for live is the
    user mode × key pairing × hello × phase.yaml, not this type check."""
    order = Signer().validate(_intent(trading_mode=mode))
    assert order.trading_mode == mode


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

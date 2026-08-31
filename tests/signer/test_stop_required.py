"""Intent without stop is rejected. No send."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from capitalizator.signer.validate import Signer, UnsignedIntent


def test_missing_stop_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UnsignedIntent.model_validate(
            {
                "symbol": "BTCUSDT",
                "side": "buy",
                "qty": "0.001",
                "limit_px": "60000",
                "trading_mode": "testnet",
            }
        )


def test_zero_stop_is_rejected() -> None:
    raw = UnsignedIntent(
        symbol="BTCUSDT",
        side="buy",
        qty=Decimal("0.001"),
        limit_px=Decimal("60000"),
        stop_px=Decimal("0"),
        trading_mode="testnet",
    )
    with pytest.raises(ValueError, match="stop"):
        Signer().validate(raw)

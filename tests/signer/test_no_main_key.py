"""4.18.2 paper — signer is testnet-only. No main key. No send."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.recorder.scan_keys import scan_tree
from capitalizator.signer.validate import Signer, UnsignedIntent

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "signer"


def test_mainnet_literal_is_a_venue() -> None:
    raw = UnsignedIntent.model_validate(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "qty": "0.001",
            "limit_px": "60000",
            "stop_px": "59400",
            "trading_mode": "mainnet",
        }
    )
    assert raw.trading_mode == "mainnet"


def test_live_mode_rejected() -> None:
    with pytest.raises(Exception, match="testnet|literal|mainnet"):
        UnsignedIntent.model_validate(
            {
                "symbol": "BTCUSDT",
                "side": "buy",
                "qty": "0.001",
                "limit_px": "60000",
                "stop_px": "59400",
                "trading_mode": "live",
            }
        )


def test_signer_source_has_no_env_key_needles() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in SRC.glob("*.py"))
    assert "BYBIT_API_KEY" not in text
    assert scan_tree(SRC) == []
    paper = (SRC / "validate.py").read_text(encoding="utf-8")
    assert "api.bybit.com" not in paper
    assert Signer  # validate does not send

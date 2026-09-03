"""Demo adapter has no mainnet host. phase.yaml=off → no send."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.exec.demo_adapter import DemoAdapter
from capitalizator.signer.validate import UnsignedIntent

ROOT = Path(__file__).resolve().parents[2] / "src" / "capitalizator"
SRC = ROOT / "exec" / "demo_adapter.py"
DEMO_TREE = (ROOT / "exec", ROOT / "signer")


def _intent() -> UnsignedIntent:
    return UnsignedIntent(
        symbol="BTCUSDT",
        side="buy",
        qty=Decimal("0.001"),
        limit_px=Decimal("60000"),
        stop_px=Decimal("59400"),
        trading_mode="testnet",
    )


def test_source_has_no_mainnet_host() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "api.bybit.com" not in text
    assert "stream.bybit.com" not in text
    allowed = {"bybit_rest.py"}
    for tree in DEMO_TREE:
        for path in tree.rglob("*.py"):
            if path.name in allowed:
                continue
            body = path.read_text(encoding="utf-8")
            assert "api.bybit.com" not in body, path
            assert "stream.bybit.com" not in body, path


def test_phase_off_does_not_submit() -> None:
    with pytest.raises(ValueError, match="not demo"):
        DemoAdapter().submit(_intent())


def test_injected_demo_mode_is_not_sent() -> None:
    out = DemoAdapter(trading_mode="demo").submit(_intent())
    assert out["mode"] == "demo"
    assert out["status"] == "not_sent"
    assert out["symbol"] == "BTCUSDT"
    assert out["stop_px"] == "59400"


def test_demo_still_requires_stop() -> None:
    raw = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "qty": "0.001",
        "limit_px": "60000",
        "trading_mode": "testnet",
    }
    with pytest.raises(Exception, match="stop"):
        UnsignedIntent.model_validate(raw)

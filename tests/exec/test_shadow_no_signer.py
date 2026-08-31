"""4.17.1 paper — shadow records an idea. Signer is not imported."""

from __future__ import annotations

from pathlib import Path

from capitalizator.exec.shadow import ShadowWriter

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec" / "shadow.py"


def test_write_is_not_sent() -> None:
    got = ShadowWriter().write({"symbol": "BTCUSDT", "tag": "bounce"})
    assert got["mode"] == "shadow"
    assert got["sent"] is False


def test_source_does_not_import_signer() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "capitalizator.signer" not in text
    assert "Signer" not in text
    assert "api.bybit.com" not in text
    assert "create_order" not in text

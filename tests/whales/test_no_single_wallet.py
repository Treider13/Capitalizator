"""3.15.4 — sole whale claim is never an entry. No invented wallets."""

from __future__ import annotations

from pathlib import Path

from capitalizator.whales.no_single import sole_whale, whale_accepts

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator"


def test_whale_voice_never_accepts() -> None:
    assert whale_accepts() is False


def test_sole_whale_claim_is_blocked() -> None:
    assert sole_whale([{"type": "whale", "value": "0xabc bought"}]) is True
    assert sole_whale([{"type": "whale_bought"}]) is True


def test_mixed_claims_are_not_sole_whale() -> None:
    assert sole_whale([{"type": "zone"}, {"type": "whale"}]) is False


def test_empty_is_not_a_whale_signal() -> None:
    assert sole_whale([]) is False


def test_propose_does_not_import_whales() -> None:
    text = (SRC / "exec" / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "capitalizator.whales" not in text
    assert "whale_accepts" not in text
    assert "hl_ingest" not in text


def test_no_hl_ingest_module() -> None:
    assert not (SRC / "whales" / "hl_ingest.py").is_file()

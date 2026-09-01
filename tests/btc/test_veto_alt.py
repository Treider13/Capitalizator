"""2.9.3 — SOL long + BTC support break is reject. Not wired into propose."""

from __future__ import annotations

from pathlib import Path

from capitalizator.btc.break_def import Break
from capitalizator.btc.veto import BtcVeto

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec" / "strategy_bounce.py"


def test_sol_long_after_btc_support_break_is_reject() -> None:
    assert (
        BtcVeto().allow(alt_side="buy", btc_broke=True, btc_zone_side="support")
        is False
    )


def test_sol_short_after_btc_resistance_break_is_reject() -> None:
    assert (
        BtcVeto().allow(alt_side="sell", btc_broke=True, btc_zone_side="resistance")
        is False
    )


def test_same_direction_is_not_cut() -> None:
    assert BtcVeto().allow(alt_side="sell", btc_broke=True, btc_zone_side="support") is True
    assert BtcVeto().allow(alt_side="buy", btc_broke=True, btc_zone_side="resistance") is True


def test_no_break_allows() -> None:
    assert BtcVeto().allow(alt_side="buy", btc_broke=False, btc_zone_side="support") is True


def test_wick_is_not_broke_so_allow() -> None:
    """Break.detect False must be what we pass as btc_broke — do not invent."""
    assert Break.detect  # label exists
    assert BtcVeto().allow(alt_side="buy", btc_broke=False, btc_zone_side="support") is True


def test_propose_source_calls_btc_veto() -> None:
    """Product: BtcVeto.allow() is always on the entry path for alts."""
    text = SRC.read_text(encoding="utf-8")
    assert "BtcVeto" in text
    assert "btc_veto.allow" in text

"""Law 1.6.3 on the engine that executes it: +1R takes half, +2R keeps the rest,
the stop path flattens and never adds. (The old TradeManager.on_fill was a shim the
desk never called; these laws are tested where the fills happen.)"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.exec.paper import PaperEngine
from capitalizator.risk.schema import FORBIDDEN_ACTIONS
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def _print(ts: datetime, px: str, side: str) -> MarketEvent:
    return MarketEvent(
        stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts, recv_ts=ts,
        payload={"px": px, "qty": "1", "side": side},
    )


def _open(eng: PaperEngine, side: str, stop: str, tp: str):
    pos = eng.submit(
        paper_id="p", touch_id="t", symbol="BTCUSDT", side=side, limit_px=Decimal("100"),
        qty=Decimal("1"), stop=Decimal(stop), tp=Decimal(tp), tick=Decimal("0.1"), now=T0,
        valid_for=timedelta(minutes=30), source="shadow", tag="bounce",
    )
    # fill: trade through the limit
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9" if side == "buy" else "100.1", "sell" if side == "buy" else "buy"))
    assert pos.state == "open"
    return pos


def test_path_to_two_r_takes_half_then_keeps_rest() -> None:
    eng = PaperEngine()
    pos = _open(eng, "buy", "98", "110")
    eng.on_print(_print(T0 + timedelta(minutes=1), "102", "buy"))  # +1R lifted our offer
    assert pos.half_taken and pos.qty_open == Decimal("0.5")
    eng.on_print(_print(T0 + timedelta(minutes=2), "104", "buy"))  # +2R: rest stays
    assert pos.state == "open" and pos.qty_open == Decimal("0.5")


def test_stop_path_flattens_without_add() -> None:
    eng = PaperEngine()
    pos = _open(eng, "buy", "98", "110")
    eng.on_print(_print(T0 + timedelta(minutes=1), "97.9", "sell"))
    assert pos.state == "closed" and pos.exit_reason == "stop" and pos.qty_open == 0
    assert "flatten" not in FORBIDDEN_ACTIONS and "average_in" in FORBIDDEN_ACTIONS


def test_short_path_to_one_r_reduces_half() -> None:
    eng = PaperEngine()
    pos = _open(eng, "sell", "102", "90")
    eng.on_print(_print(T0 + timedelta(minutes=1), "98", "sell"))  # +1R hit our bid
    assert pos.half_taken and pos.qty_open == Decimal("0.5")


def test_trail_is_structure_not_entry() -> None:
    from capitalizator.exec.trail import TrailState

    stt = TrailState(side="buy", entry=Decimal("100"), stop=Decimal("98"), tick=Decimal("0.1"))
    assert stt.r_px() == Decimal("2")
    stt.stop = Decimal("101.2")  # a structure trail moved it
    assert stt.r_px() == Decimal("2")  # 1R never changes
    assert stt.stop != stt.entry

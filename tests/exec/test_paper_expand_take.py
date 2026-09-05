"""+1R take follows hyexec FLOOR/EXPAND. Floor is half. Expand is 30%."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.exec.paper import PaperEngine
from capitalizator.hyexec.expand import EXPAND_TAKE, FLOOR_TAKE

T0 = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def _print(ts: datetime, px: str, side: str = "buy") -> object:
    from capitalizator.types import MarketEvent

    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "0.1", "side": side},
    )


def _fill_buy(engine: PaperEngine, **over):
    args = dict(
        paper_id="t1:shadow",
        touch_id="t1",
        symbol="BTCUSDT",
        side="buy",
        limit_px=Decimal("100"),
        qty=Decimal("1"),
        stop=Decimal("98"),
        tp=Decimal("104"),
        tick=Decimal("0.1"),
        now=T0,
        valid_for=timedelta(minutes=30),
        source="shadow",
        tag="bounce",
    )
    args.update(over)
    pos = engine.submit(**args)
    engine.on_print(_print(T0 + timedelta(seconds=1), "99.9", side="sell"))
    return pos


def test_floor_take_leaves_half() -> None:
    eng = PaperEngine()
    pos = _fill_buy(eng, labels={"expand": False})
    eng.on_print(_print(T0 + timedelta(minutes=1), "102", side="buy"))
    assert pos.half_taken
    assert pos.qty_open == Decimal("1") * (1 - FLOOR_TAKE)


def test_expand_take_leaves_seventy() -> None:
    eng = PaperEngine()
    pos = _fill_buy(eng, labels={"expand": True})
    eng.on_print(_print(T0 + timedelta(minutes=1), "102", side="buy"))
    assert pos.half_taken
    assert pos.qty_open == Decimal("1") * (1 - EXPAND_TAKE)
    assert pos.qty_open == Decimal("0.7")

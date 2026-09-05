"""Desk applies the served score to a FLOOR remainder. EXPAND still holds."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello
from capitalizator.ops.vault import init_vault
from capitalizator.types import MarketEvent

TICK = Decimal("0.1")
WHEN = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def _trade(ts: datetime, px: str, side: str = "sell", qty: str = "1000") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": qty, "side": side},
    )


def _desk(tmp_path: Path) -> DeskLoop:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    return DeskLoop(knowledge=open_knowledge(vault), user_mode="demo", tick_size=TICK)


def _fill_half(desk: DeskLoop, *, labels: dict) -> object:
    pos = desk.paper.submit(
        paper_id="t1:demo",
        touch_id="t1",
        symbol="BTCUSDT",
        side="buy",
        limit_px=Decimal("100"),
        qty=Decimal("1"),
        stop=Decimal("98"),
        tp=Decimal("104"),
        tick=TICK,
        now=WHEN,
        valid_for=timedelta(minutes=30),
        source="demo",
        tag="bounce",
        structural=Decimal("98"),
        labels=labels,
    )
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    desk.on_trade(_trade(WHEN + timedelta(minutes=1), "102", side="buy"), [])
    return pos


def test_desk_tick_flattens_floor_remainder_on_score_drop(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    pos = _fill_half(desk, labels={"score_entry": "0.70", "expand": False})
    assert pos.half_taken and pos.state == "open"
    desk.knowledge.set_meta(
        "hyexec_serve",
        json.dumps({"by_symbol": {"BTCUSDT": {"score": 0.40, "model_go": True}}}),
    )
    desk.last_price["BTCUSDT"] = Decimal("101")
    desk.tick(WHEN + timedelta(minutes=3))
    assert pos.state == "closed"
    assert pos.exit_reason == "score"


def test_desk_tick_holds_expand_remainder_on_score_drop(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    pos = _fill_half(desk, labels={"score_entry": "0.70", "expand": True})
    desk.knowledge.set_meta(
        "hyexec_serve",
        json.dumps({"by_symbol": {"BTCUSDT": {"score": 0.40, "model_go": False}}}),
    )
    desk.last_price["BTCUSDT"] = Decimal("101")
    desk.tick(WHEN + timedelta(minutes=3))
    assert pos.state == "open"
    assert pos.qty_open > 0

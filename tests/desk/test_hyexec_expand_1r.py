"""+1R take follows live expand_ok. A submit stamp is not the clock."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.expand import EXPAND_TAKE, FLOOR_TAKE
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
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


def _desk(tmp_path: Path, mode: str = "demo") -> DeskLoop:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    return DeskLoop(knowledge=open_knowledge(vault), user_mode=mode, tick_size=TICK)


def _bid_heavy_book(when: datetime) -> Book:
    bids = tuple((str(Decimal("100") - TICK * i), "50") for i in range(1, 6))
    asks = tuple((str(Decimal("100") + TICK * i), "5") for i in range(1, 6))
    book = Book(tick_size=str(TICK))
    book.apply_snapshot(
        BookSnapshot(symbol="BTCUSDT", exchange_ts=when, seq=1, bids=bids, asks=asks)
    )
    return book


def _submit_demo(desk: DeskLoop, *, labels: dict | None = None) -> object:
    return desk.paper.submit(
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
        labels=labels or {},
    )


def _plus_day(desk: DeskLoop, when: datetime) -> None:
    start = desk.account.equity
    desk.account.set_equity(
        start * Decimal("1.03"), source=desk.account.equity_source, now=when
    )
    desk._sync_window_halt(when)


def test_submit_expand_stamp_is_ignored_when_day_is_flat(tmp_path: Path) -> None:
    """EXPAND at entry is the wrong clock. Flat day stays FLOOR even if stamped."""
    desk = _desk(tmp_path)
    pos = _submit_demo(desk, labels={"expand": True})
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    assert pos.state == "open"
    desk.on_trade(_trade(WHEN + timedelta(minutes=1), "102", side="buy"), [])
    assert pos.half_taken
    assert pos.qty_open == Decimal("1") * (1 - FLOOR_TAKE)
    assert pos.qty_open == Decimal("0.5")


def test_live_expand_at_1r_leaves_seventy_on_paper(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _plus_day(desk, WHEN)
    desk.on_book("BTCUSDT", _bid_heavy_book(WHEN))
    pos = _submit_demo(desk)
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    assert pos.state == "open"
    desk.on_trade(_trade(WHEN + timedelta(minutes=1), "102", side="buy"), [])
    assert pos.half_taken
    assert pos.qty_open == Decimal("1") * (1 - EXPAND_TAKE)
    assert pos.qty_open == Decimal("0.7")


def test_venue_half_tp_uses_expand_take_when_live_ok(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo")
    _plus_day(desk, WHEN)
    desk.on_book("BTCUSDT", _bid_heavy_book(WHEN))
    _submit_demo(desk)
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    half = next(c for c in desk.knowledge.oms_rows() if c["kind"] == "half_tp")
    assert Decimal(half["payload"]["qty"]) == EXPAND_TAKE


def test_overlap_half_tp_stamps_harvest_only_after_take(tmp_path: Path) -> None:
    """Text says the window took a piece. Resting the +1R order is not that."""
    desk = _desk(tmp_path, "demo")
    desk.on_book("BTCUSDT", _bid_heavy_book(WHEN))
    pos = _submit_demo(desk)
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    assert pos.state == "open" and not pos.half_taken
    assert desk.knowledge.meta("hyexec_event") is None
    desk.on_trade(_trade(WHEN + timedelta(minutes=1), "102", side="buy"), [])
    assert pos.half_taken
    raw = desk.knowledge.meta("hyexec_event")
    assert raw is not None
    assert json.loads(raw)["kind"] == "harvest"


def test_expand_label_freezes_after_the_1r_take(tmp_path: Path) -> None:
    """Day later going flat is not a new take clock. Score reads this label."""
    desk = _desk(tmp_path)
    _plus_day(desk, WHEN)
    desk.on_book("BTCUSDT", _bid_heavy_book(WHEN))
    pos = _submit_demo(desk)
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    desk.on_trade(_trade(WHEN + timedelta(minutes=1), "102", side="buy"), [])
    assert pos.half_taken
    assert pos.labels["expand"] is True
    assert pos.qty_open == Decimal("1") * (1 - EXPAND_TAKE)
    desk.account.set_equity(
        desk.window_halt.start, source=desk.account.equity_source, now=WHEN
    )
    desk._sync_window_halt(WHEN)
    desk.on_trade(_trade(WHEN + timedelta(minutes=2), "103", side="buy"), [])
    assert pos.labels["expand"] is True
    assert pos.state == "open"


def test_venue_half_tp_stays_floor_when_day_is_flat(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo")
    desk.on_book("BTCUSDT", _bid_heavy_book(WHEN))
    _submit_demo(desk, labels={"expand": True})
    desk.on_trade(_trade(WHEN + timedelta(seconds=1), "99.9"), [])
    half = next(c for c in desk.knowledge.oms_rows() if c["kind"] == "half_tp")
    assert Decimal(half["payload"]["qty"]) == FLOOR_TAKE

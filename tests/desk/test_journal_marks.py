"""Desk stamps sweep_wick / fvg_present. no_tvh when tape is missing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.exec.tvh import NO_TVH
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
WINDOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _desk(tmp_path) -> DeskLoop:
    vault = init_vault(tmp_path / "marks")
    return DeskLoop(
        knowledge=open_knowledge(vault),
        user_mode="off",
        tick_size=TICK,
    )


def _book() -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            seq=1,
            bids=(("100.4", "20"),),
            asks=(("100.6", "20"),),
        )
    )
    return book


def _trade() -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=WINDOW,
        recv_ts=WINDOW,
        seq=None,
        payload={"px": "100.5", "qty": "1", "side": "sell"},
    )


def _bar(*, low: str = "99.5", close: str = "100.4") -> Bar:
    ts = WINDOW + timedelta(minutes=15)
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=WINDOW,
        close_ts=ts,
        open=Decimal("100.5"),
        high=Decimal("101"),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_failed_break_journals_sweep_wick(tmp_path) -> None:
    desk = _desk(tmp_path)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar())
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["idea"] == "failed_break"
    assert row["sweep_wick"] is True
    assert row["fvg_present"] is None


def test_unknown_tape_skips_no_tvh(tmp_path) -> None:
    desk = _desk(tmp_path)
    desk.on_trade(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(low="100.2", close="100.6"))
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["skip_reason"] == NO_TVH
    assert row["shadow_would"] is False
    assert events[0]["sent"] is False

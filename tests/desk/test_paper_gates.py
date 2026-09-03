"""Э6: paper modules run on every jury touch. They do not open size."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.desk.paper_gates import snapshot
from capitalizator.memory.registry import Touch
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello
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


def test_paper_gates_all_refuse_and_nmin_f1_is_one() -> None:
    snap = snapshot(n_zlg=0, gesture="SILENCE")
    assert snap["reaction_opens"] is False
    assert snap["pit_accepts"] is False
    assert snap["weight_opens"] is False
    assert snap["oko_opens"] is False
    assert snap["nmin_mult"] == "1"


def test_journal_has_paper_gates(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    for i in range(20):
        desk.registry.touches.append(
            replace(
                Touch.create(
                    zone_id=ZONE.zone_id,
                    ts=CREATED + timedelta(seconds=i + 1),
                    trade_px=Decimal("100.5"),
                    trade_qty=Decimal("1"),
                ),
                outcome="bounce",
                cav_label="REJECT",
                gesture="DEFEND",
                tape_eaten=False,
                btc_regime="box",
            )
        )
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
    desk.on_book("BTCUSDT", book)
    desk.on_trade(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            payload={"px": "100.5", "qty": "1", "side": "sell"},
        ),
        [ZONE],
    )
    live = desk.state_for("BTCUSDT").last_touch
    assert live is not None
    desk.registry._patch(touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED")
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=WINDOW,
            close_ts=WINDOW + timedelta(minutes=15),
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("100.2"),
            close=Decimal("100.6"),
        )
    )
    assert events
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    gates = row["paper_gates"]
    assert gates["reaction_opens"] is False
    assert gates["pit_accepts"] is False
    assert gates["weight_opens"] is False
    assert gates["oko_opens"] is False
    assert gates["nmin_mult"] == "1"

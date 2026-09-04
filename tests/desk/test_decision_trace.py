"""Э5: DecisionTrace journals A/B/C + intel/sentiment/whales on the touch."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.memory.registry import Touch
from capitalizator.ops.decision_trace import DecisionTrace
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


def test_trace_payload_has_all_contours() -> None:
    trace = DecisionTrace(
        touch_id="t1",
        symbol="BTCUSDT",
        closed_at=WINDOW.isoformat(),
        contour_a="ACCORD",
        contour_b="b_veto",
        contour_c="silent",
        intel="coin_negative",
        sentiment="monthly_greed",
        whales="ok",
        skip_reason="b_veto",
        decision_ms=12.0,
    )
    body = trace.to_payload()
    assert body["contour_a"] == "ACCORD"
    assert body["contour_b"] == "b_veto"
    assert body["intel"] == "coin_negative"


def test_jury_journals_decision_trace(tmp_path: Path) -> None:
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
    trace = row["decision_trace"]
    assert trace["touch_id"] == events[0]["touch_id"]
    assert trace["contour_a"] == row["jury"]
    assert "contour_b" in trace
    assert "sentiment" in trace
    assert "whales" in trace
    raw = desk.knowledge.meta("decision_trace")
    assert raw is not None
    assert json.loads(raw)["touch_id"] == events[0]["touch_id"]

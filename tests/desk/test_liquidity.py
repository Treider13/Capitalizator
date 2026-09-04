"""Э7: liquidity facts (multi-level OFI, CVD, AMD phase, book check) on the journal.

They do not open size. A crossed book is a skip, not a chase.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.memory.registry import Touch
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello
from capitalizator.ops.vault import init_vault
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


def _seed(desk: DeskLoop) -> None:
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


def _ev(
    stream: str,
    *,
    ts: datetime,
    seq: int | None = None,
    payload: dict | None = None,
) -> MarketEvent:
    return MarketEvent(
        stream=stream,  # type: ignore[arg-type]
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=seq,
        payload=payload or {},
    )


def _close(desk: DeskLoop) -> dict:
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
    return row


def test_journal_has_liquidity_facts(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    _seed(desk)
    desk.on_event(
        _ev(
            "snapshot",
            ts=WINDOW,
            seq=1,
            payload={
                "bids": [["100.4", "20"], ["100.3", "8"]],
                "asks": [["100.6", "20"], ["100.7", "8"]],
            },
        )
    )
    desk.on_event(
        _ev("trades", ts=WINDOW, payload={"px": "100.5", "qty": "1", "side": "sell"}),
        [ZONE],
    )
    # L2 bid 8→11, L1 unchanged: L1 OFI = 0, two-level OFI = +3.
    desk.on_event(
        _ev("book_diff", ts=WINDOW + timedelta(seconds=1), seq=2, payload={"bids": [["100.3", "11"]], "asks": []})
    )
    row = _close(desk)
    liq = row["liquidity"]
    assert liq["book_ok"] is True
    assert liq["book_reason"] is None
    assert liq["cvd"] == "-1"
    assert liq["ofi"] == "0"
    assert liq["ofi_levels"] == "3"
    assert row["ofi"] == "0"
    assert liq["phase"] in {"accumulate", "manipulate", "distribute", "unknown"}


def test_journal_keeps_touch_window_liquidity_after_later_book(tmp_path: Path) -> None:
    """Live diffs after ZLG slide book_history. The journal must keep the 8s stamp."""
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    _seed(desk)
    desk.on_event(
        _ev(
            "snapshot",
            ts=WINDOW,
            seq=1,
            payload={
                "bids": [["100.4", "20"], ["100.3", "8"]],
                "asks": [["100.6", "20"], ["100.7", "8"]],
            },
        )
    )
    desk.on_event(
        _ev("trades", ts=WINDOW, payload={"px": "100.5", "qty": "1", "side": "sell"}),
        [ZONE],
    )
    desk.on_event(
        _ev("book_diff", ts=WINDOW + timedelta(seconds=1), seq=2, payload={"bids": [["100.3", "11"]], "asks": []})
    )
    desk.tick(WINDOW + timedelta(seconds=8))
    later = WINDOW + timedelta(minutes=5)
    for i in range(5):
        desk.on_event(
            _ev(
                "book_diff",
                ts=later + timedelta(seconds=i),
                seq=3 + i,
                payload={"bids": [["100.4", str(20 + i)]], "asks": []},
            )
        )
    st = desk.state_for("BTCUSDT")
    live = st.last_touch
    assert live is not None
    _, path = desk._touch_window(st, live, seconds=8)
    assert path == []
    desk.registry._patch(touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED")
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
    liq = row["liquidity"]
    assert liq["ofi"] == "0"
    assert liq["ofi_levels"] == "3"
    assert row["ofi"] == "0"
    assert liq["cvd"] == "-1"
    assert liq["book_ok"] is True


def test_crossed_book_journals_not_ok(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    _seed(desk)
    desk.on_event(
        _ev(
            "snapshot",
            ts=WINDOW,
            seq=1,
            payload={"bids": [["101", "10"]], "asks": [["100", "10"]]},
        )
    )
    desk.on_event(
        _ev("trades", ts=WINDOW, payload={"px": "100.5", "qty": "1", "side": "sell"}),
        [ZONE],
    )
    row = _close(desk)
    liq = row["liquidity"]
    assert liq["book_ok"] is False
    assert liq["book_reason"] == "crossed"
    assert liq["ofi"] is None
    assert liq["ofi_levels"] is None
    assert liq["cvd"] == "-1"
    assert liq["phase"] == "unknown"

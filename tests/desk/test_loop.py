"""Desk organism: per-symbol machine, book_pre, shadow always, send only gated."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop, _close_symbols
from capitalizator.memory.registry import Touch
from capitalizator.news_macro.ingest import NewsIngest, default_macro_path
from capitalizator.news_macro.unlocks import UnlockRow, Unlocks
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.risk.sessions import SessionPolicy
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
ETH_ZONE = Zone.create(
    symbol="ETHUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _trade(ts: datetime, symbol: str = "BTCUSDT") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": "100.5", "qty": "1", "side": "sell"},
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


def _bar(ts: datetime, symbol: str = "BTCUSDT") -> Bar:
    return Bar(
        symbol=symbol,
        tf="15m",
        open_ts=ts - timedelta(minutes=15),
        close_ts=ts,
        open=Decimal("100.5"),
        high=Decimal("101"),
        low=Decimal("100.2"),
        close=Decimal("100.6"),
    )


def test_symbols_are_independent(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_book("BTCUSDT", _book())
    desk.on_book("ETHUSDT", _book())
    desk.on_trade(_trade(WINDOW, "BTCUSDT"), [ZONE])
    desk.on_trade(_trade(WINDOW, "ETHUSDT"), [ETH_ZONE])
    assert desk.state_for("BTCUSDT").state == "ARM_ZLG"
    assert desk.state_for("ETHUSDT").state == "ARM_ZLG"
    desk.tick(WINDOW + timedelta(seconds=8))
    assert desk.state_for("BTCUSDT").state == "LABEL_ZLG"
    assert desk.state_for("ETHUSDT").state == "LABEL_ZLG"


def test_book_pre_is_frozen_at_touch(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    book = _book()
    desk.on_book("BTCUSDT", book)
    desk.on_trade(_trade(WINDOW), [ZONE])
    pre = desk.state_for("BTCUSDT").book_pre
    assert pre is not None
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            seq=2,
            bids=(("100.4", "1"),),
            asks=(("100.6", "20"),),
        )
    )
    assert pre.level("bid", "100.4") == Decimal("20")
    assert book.level("bid", "100.4") == Decimal("1")


def test_demo_window_enqueues_after_accord(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="demo", tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    for i in range(20):
        touch = replace(
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
        desk.registry.touches.append(touch)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(WINDOW), [ZONE])
    live = desk.state_for("BTCUSDT").last_touch
    assert live is not None
    desk.registry._patch(
        touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED"
    )
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert events
    journal = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert journal is not None
    if journal["jury"] == "ACCORD":
        assert events[0]["sent"] is True
        assert desk.knowledge.pending_intents()
    else:
        assert events[0]["sent"] is False


def test_team_unlock_tomorrow_does_not_send(tmp_path: Path) -> None:
    """Unlocks.team_* already cuts the screener. Desk used to pass default False."""
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    unlocks = Unlocks(
        (
            UnlockRow(
                unlock_id="btc-2026-09-01",
                symbol="BTCUSDT",
                event_time=datetime(2026, 9, 1, tzinfo=UTC),
                known_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
                recipient_type="team",
                amount_tokens=Decimal("1"),
                amount_usd_est=Decimal("1"),
                source="fixture",
            ),
        )
    )
    assert unlocks.team_tomorrow("BTCUSDT", WINDOW) is True
    desk = DeskLoop(
        knowledge=open_knowledge(vault),
        user_mode="demo",
        tick_size=TICK,
        unlocks=unlocks,
    )
    desk.registry._zones[ZONE.zone_id] = ZONE
    for i in range(20):
        touch = replace(
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
        desk.registry.touches.append(touch)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(WINDOW), [ZONE])
    live = desk.state_for("BTCUSDT").last_touch
    assert live is not None
    desk.registry._patch(
        touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED"
    )
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert events
    assert events[0]["sent"] is False
    assert desk.knowledge.pending_intents() == []


def test_snapshot_event_applies_to_book(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            seq=1,
            payload={"bids": [["100.4", "20"]], "asks": [["100.6", "20"]]},
        )
    )
    book = desk.state_for("BTCUSDT").book
    assert book.ready is True
    assert book.best() == (Decimal("100.4"), Decimal("100.6"))


def test_book_diff_after_touch_is_zlg_defend(tmp_path: Path) -> None:
    """§6.4 / wave 3: tape book_diff must become BookAdd. Else VPS ZLG is always SILENCE."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            seq=1,
            payload={"bids": [["100.4", "20"]], "asks": [["100.6", "20"]]},
        )
    )
    desk.on_event(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            payload={"px": "100.4", "qty": "1", "side": "sell"},
        ),
        [ZONE],
    )
    desk.on_event(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW + timedelta(seconds=1),
            recv_ts=WINDOW + timedelta(seconds=1),
            seq=2,
            payload={"bids": [["100.4", "25"]], "asks": []},
        )
    )
    events = desk.tick(WINDOW + timedelta(seconds=8))
    assert events
    assert events[0]["gesture"] == "DEFEND"
    st = desk.state_for("BTCUSDT")
    assert st.adds
    assert st.adds[0].qty == Decimal("5")


def test_btc_htf_close_writes_regime_bus(tmp_path: Path) -> None:
    """§6.7: BTC loop writes BtcBus. Else alts never see regime and BtcVeto is dead."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    day = datetime(2026, 8, 30, tzinfo=UTC)
    for hour, high, low, close in ((0, "10", "8", "9"), (4, "11", "8", "10"), (8, "20", "12", "19")):
        desk.on_bar_close(
            Bar(
                symbol="BTCUSDT",
                tf="4h",
                open_ts=day.replace(hour=hour),
                close_ts=day.replace(hour=hour + 4),
                open=Decimal(close),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
            )
        )
    assert desk.btc.regime == "trend"


def _h4_trend(desk: DeskLoop, day: datetime) -> None:
    for hour, high, low, close in ((0, "10", "8", "9"), (4, "11", "8", "10"), (8, "20", "12", "19")):
        desk.on_bar_close(
            Bar(
                symbol="BTCUSDT",
                tf="4h",
                open_ts=day.replace(hour=hour),
                close_ts=day.replace(hour=hour + 4),
                open=Decimal(close),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
            )
        )


def test_loaded_calendar_is_not_news_on_a_quiet_day(tmp_path: Path) -> None:
    """known_at of next month's CPI is not this bar's news. HTF still speaks."""
    vault = init_vault(tmp_path / "desk")
    cal = tuple(NewsIngest.from_csv(default_macro_path()).rows)
    desk = DeskLoop(
        knowledge=open_knowledge(vault),
        user_mode="off",
        tick_size=TICK,
        calendar=cal,
    )
    _h4_trend(desk, datetime(2026, 9, 2, tzinfo=UTC))
    assert desk.btc.regime == "trend"


def test_us_data_day_marks_btc_news(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    cal = tuple(NewsIngest.from_csv(default_macro_path()).rows)
    desk = DeskLoop(
        knowledge=open_knowledge(vault),
        user_mode="off",
        tick_size=TICK,
        calendar=cal,
    )
    _h4_trend(desk, datetime(2026, 9, 11, tzinfo=UTC))
    assert desk.btc.regime == "news"


def test_btc_touch_stamps_bus_news_not_local_h4(tmp_path: Path) -> None:
    """CPI day: bus is news. Painting the BTC touch from H4 would be a lie."""
    vault = init_vault(tmp_path / "desk")
    cal = tuple(NewsIngest.from_csv(default_macro_path()).rows)
    desk = DeskLoop(
        knowledge=open_knowledge(vault),
        user_mode="off",
        tick_size=TICK,
        calendar=cal,
    )
    day = datetime(2026, 9, 11, tzinfo=UTC)
    _h4_trend(desk, day)
    assert desk.btc.regime == "news"
    ts = day.replace(hour=14, minute=10)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(ts), [ZONE])
    desk.tick(ts + timedelta(seconds=8))
    events = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=ts,
            close_ts=ts + timedelta(minutes=15),
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("100.2"),
            close=Decimal("100.6"),
        )
    )
    # B-card may veto on CPI at ZLG; the bus stamp is already on the touch.
    row = desk.registry.touches[-1]
    assert row.btc_regime == "news"
    assert desk.btc.regime == "news"
    if events:
        assert events[0]["touch_id"] == row.touch_id


def test_btc_bus_does_not_keep_yesterdays_news(tmp_path: Path) -> None:
    """A later unknown HTF close must not keep a latched news label."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.btc.regime = "news"
    desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert desk.btc.regime is None


def test_alt_touch_does_not_paint_btc_from_own_htf(tmp_path: Path) -> None:
    """ETH H4 is not the BTC bus. Empty bus stays None on the alt touch."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    day = datetime(2026, 8, 30, tzinfo=UTC)
    for hour, high, low, close in (
        (0, "10", "8", "9"),
        (4, "11", "8", "10"),
        (8, "20", "12", "19"),
    ):
        desk.on_bar_close(
            Bar(
                symbol="ETHUSDT",
                tf="4h",
                open_ts=day.replace(hour=hour),
                close_ts=day.replace(hour=hour + 4),
                open=Decimal(close),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
            )
        )
    assert desk.btc.regime is None
    desk.on_book("ETHUSDT", _book())
    desk.on_trade(_trade(WINDOW, "ETHUSDT"), [ETH_ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15), "ETHUSDT"))
    assert events
    row = next(t for t in desk.registry.touches if t.touch_id == events[0]["touch_id"])
    assert row.btc_regime is None


def test_alt_touch_copies_published_btc_bus(tmp_path: Path) -> None:
    """play() closes BTC first so the alt jury sees the bus, not ETH candles."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    _h4_trend(desk, datetime(2026, 8, 30, tzinfo=UTC))
    assert desk.btc.regime == "trend"
    desk.on_book("ETHUSDT", _book())
    desk.on_trade(_trade(WINDOW, "ETHUSDT"), [ETH_ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15), "ETHUSDT"))
    assert events
    row = next(t for t in desk.registry.touches if t.touch_id == events[0]["touch_id"])
    assert row.btc_regime == "trend"


def test_stale_eaten_touch_is_not_this_bar_btc_break(tmp_path: Path) -> None:
    """Close beyond + last week's eaten is not 2.9.2. Eaten must sit in this bar."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    desk.registry.touches.append(
        replace(
            Touch.create(
                zone_id=ZONE.zone_id,
                ts=CREATED + timedelta(hours=1),
                trade_px=Decimal("100.5"),
                trade_qty=Decimal("1"),
            ),
            outcome="break",
            tape_eaten=True,
        )
    )
    desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=WINDOW - timedelta(minutes=15),
            close_ts=WINDOW,
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("99"),
        )
    )
    assert desk.btc.broke_support is False


def test_eaten_touch_in_bar_and_close_beyond_is_btc_break(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    desk.registry.touches.append(
        replace(
            Touch.create(
                zone_id=ZONE.zone_id,
                ts=WINDOW - timedelta(minutes=5),
                trade_px=Decimal("100.5"),
                trade_qty=Decimal("1"),
            ),
            outcome="pending",
            tape_eaten=True,
        )
    )
    desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=WINDOW - timedelta(minutes=15),
            close_ts=WINDOW,
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("99"),
        )
    )
    assert desk.btc.broke_support is True


def test_desk_btc_same_side_uses_bus_direction_not_a_rubber_stamp() -> None:
    """Same side = the bus direction (HTF bias of closed BTC bars) agrees with the idea,
    or BTC is in a box. BTCUSDT itself gets no free pass, and a regime label alone
    never means "same side"."""
    text = Path(__file__).resolve().parents[2].joinpath(
        "src", "capitalizator", "desk", "loop.py"
    ).read_text(encoding="utf-8")
    assert "btc_same_side = self.btc_same_side(idea_side)" in text
    assert "st.symbol == \"BTCUSDT\" or self.btc.regime" not in text
    assert '{"long", "box"}' not in text
    assert '{"short", "box"}' not in text


def test_send_uses_bar_close_clock_not_touch_print(tmp_path: Path) -> None:
    """The touch prints inside an open window; the jury closes the bar in the next
    window, which is closed (sessions.yaml). Send follows the CLOSE clock."""
    policy = SessionPolicy.load()
    touch_ts = datetime(2026, 8, 31, 20, 50, tzinfo=UTC)
    close_ts = datetime(2026, 8, 31, 21, 5, tzinfo=UTC)
    open_w, next_w = policy.window(touch_ts), policy.window(close_ts)
    assert open_w.budget > 0 and next_w.budget == 0  # us → night
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="demo", tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    for i in range(20):
        touch = replace(
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
        desk.registry.touches.append(touch)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(touch_ts), [ZONE])
    live = desk.state_for("BTCUSDT").last_touch
    assert live is not None
    desk.registry._patch(
        touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED"
    )
    desk.tick(touch_ts + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(close_ts))
    assert events
    assert events[0]["sent"] is False
    assert desk.knowledge.pending_intents() == []


def test_working_bar_inside_zlg_window_waits_for_label(tmp_path: Path) -> None:
    """A 15m close 3s after the print is not a jury. Plan is ZLG then CAV."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(WINDOW), [ZONE])
    early = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=WINDOW - timedelta(minutes=15),
            close_ts=WINDOW + timedelta(seconds=3),
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("100.2"),
            close=Decimal("100.6"),
        )
    )
    assert early == []
    assert desk.state_for("BTCUSDT").state == "ARM_ZLG"
    out = desk.tick(WINDOW + timedelta(seconds=8))
    kinds = [e.get("event") for e in out]
    assert kinds.index("zlg") < kinds.index("jury")
    assert desk.state_for("BTCUSDT").state == "IDLE"


def test_cav_uses_first_closed_bar_not_latest(tmp_path: Path) -> None:
    """Two working closes before ZLG: CAV is the first bar after the print."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(WINDOW), [ZONE])
    desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=WINDOW - timedelta(minutes=15),
            close_ts=WINDOW + timedelta(seconds=3),
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("100.2"),
            close=Decimal("100.6"),
        )
    )
    desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=WINDOW + timedelta(seconds=3),
            close_ts=WINDOW + timedelta(minutes=18),
            open=Decimal("100.6"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("99"),
        )
    )
    assert desk.state_for("BTCUSDT").state == "ARM_ZLG"
    out = desk.tick(WINDOW + timedelta(seconds=8))
    assert any(e.get("event") == "jury" for e in out)
    live = [t for t in desk.registry.touches if t.ts == WINDOW]
    assert live
    assert live[-1].cav_label != "THROUGH"


def test_ofi_uses_touch_window_not_later_books(tmp_path: Path) -> None:
    """CKS OFI is the 8s touch interval. Later L2 must not replace the number."""
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            seq=1,
            payload={"bids": [["100.4", "5"]], "asks": [["100.6", "5"]]},
        )
    )
    desk.on_event(_trade(WINDOW), [ZONE])
    desk.on_event(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW + timedelta(seconds=1),
            recv_ts=WINDOW + timedelta(seconds=1),
            seq=2,
            payload={"bids": [["100.4", "8"]], "asks": []},
        )
    )
    desk.tick(WINDOW + timedelta(seconds=8))
    later = WINDOW + timedelta(minutes=10)
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=later,
            recv_ts=later,
            seq=3,
            payload={"bids": [["100.4", "5"]], "asks": [["100.6", "5"]]},
        )
    )
    desk.on_event(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=later + timedelta(seconds=1),
            recv_ts=later + timedelta(seconds=1),
            seq=4,
            payload={"bids": [["100.4", "20"]], "asks": []},
        )
    )
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert events
    row = next(t for t in desk.registry.touches if t.touch_id == events[0]["touch_id"])
    assert row.ofi == "3"


def test_later_zone_does_not_steal_armed_touch(tmp_path: Path) -> None:
    other = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(WINDOW), [ZONE])
    held = desk.state_for("BTCUSDT").last_touch
    assert held is not None
    desk.on_trade(_trade(WINDOW + timedelta(seconds=2)), [other])
    assert desk.state_for("BTCUSDT").last_touch is not None
    assert desk.state_for("BTCUSDT").last_touch.touch_id == held.touch_id
    assert any(t.zone_id == other.zone_id for t in desk.registry.touches)


def test_missing_zone_does_not_crash_n_cav(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=TICK)
    desk.registry.touches.append(
        replace(
            Touch.create(
                zone_id="ghost",
                ts=CREATED + timedelta(seconds=1),
                trade_px=Decimal("100.5"),
                trade_qty=Decimal("1"),
            ),
            outcome="bounce",
            cav_label="REJECT",
            gesture="DEFEND",
        )
    )
    desk.on_book("BTCUSDT", _book())
    desk.on_trade(_trade(WINDOW), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert events
    assert events[0]["event"] == "jury"


def test_close_symbols_puts_btc_first() -> None:
    assert _close_symbols({"ETHUSDT": None, "BTCUSDT": None}) == [
        "BTCUSDT",
        "ETHUSDT",
    ]

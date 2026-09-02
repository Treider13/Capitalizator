"""Desk × ОКО: a bid wall that appears after the print and leaves without a
print is SPOOF on the 8s clock and VETO at the jury. Clean touch → 0. No book →
UNKNOWN. Outcome teaches the immune memory. Organs persist in knowledge meta."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.oko.eye import OkoEye
from capitalizator.ops.knowledge import open_knowledge
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


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(
        knowledge=open_knowledge(init_vault(tmp_path / "desk")),
        user_mode="off",
        tick_size=TICK,
    )


def _snapshot(ts: datetime, *, bid: str = "20", seq: int = 1) -> MarketEvent:
    return MarketEvent(
        stream="snapshot",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=seq,
        payload={"bids": [["100.4", bid]], "asks": [["100.6", "20"]]},
    )


def _diff(ts: datetime, *, seq: int, bid: str) -> MarketEvent:
    return MarketEvent(
        stream="book_diff",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=seq,
        payload={"bids": [["100.4", bid]], "asks": []},
    )


def _trade(ts: datetime, *, px: str = "100.4", side: str = "sell") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "1", "side": side},
    )


def _bar(close_ts: datetime, *, close: str = "100.6", low: str = "100.2") -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=close_ts - timedelta(minutes=15),
        close_ts=close_ts,
        open=Decimal("100.5"),
        high=Decimal("101"),
        low=Decimal(low),
        close=Decimal(close),
    )


def _touch_then_wall(desk: DeskLoop, *, wall: str, back: str = "20") -> None:
    desk.on_event(_snapshot(WINDOW))
    desk.on_event(_trade(WINDOW), [ZONE])
    desk.on_event(_diff(WINDOW + timedelta(seconds=1), seq=2, bid=wall))
    desk.on_event(_diff(WINDOW + timedelta(seconds=3), seq=3, bid=back))


def test_silent_bid_wall_under_the_print_is_spoof_and_veto(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    # 20 → 45 → 20: +25 on 20 of depth, below WallWatch's 50 so only ОКО sees it.
    _touch_then_wall(desk, wall="45")
    out = desk.tick(WINDOW + timedelta(seconds=8))
    assert [e["event"] for e in out] == ["zlg"]
    live = desk.state_for("BTCUSDT").last_touch
    assert live is not None
    row = next(t for t in desk.registry.touches if t.touch_id == live.touch_id)
    assert row.oko_label == "SPOOF"
    assert row.oko_book_trust == "0.0000"
    assert row.oko_voice is None  # the voice waits for CAV
    assert desk.knowledge.meta("oko:passport:BTCUSDT") is not None
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert events and events[0]["event"] == "jury"
    assert events[0]["jury"] == "VETO"
    assert events[0]["sent"] is False
    journal = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert journal is not None
    assert journal["oko_voice"] == "VETO"
    assert journal["oko_label"] == "SPOOF"
    assert "spoof on zone side" in journal["oko_reason"]
    assert journal["oko_size_mult"] == "0"
    assert (
        journal["oko_fingerprint"] and journal["oko_fingerprint"].count("-") == 12
    )  # 10 Shadow + 3 Footprint
    assert journal["jury"] == "VETO"
    assert journal["zlg_label"] == "DEFEND"  # the book *looked* defended; ОКО saw the pull


def test_wall_that_is_eaten_is_not_a_spoof(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_event(_snapshot(WINDOW))
    desk.on_event(_trade(WINDOW), [ZONE])
    desk.on_event(_diff(WINDOW + timedelta(seconds=1), seq=2, bid="45"))
    for i in range(25):
        desk.on_event(_trade(WINDOW + timedelta(seconds=2, milliseconds=10 * i), px="100.4"), [])
    desk.on_event(_diff(WINDOW + timedelta(seconds=3), seq=3, bid="20"))
    desk.tick(WINDOW + timedelta(seconds=8))
    row = desk.registry.touches[-1]
    assert row.oko_label == "CLEAN"
    assert row.oko_book_trust == "1.0000"


def test_clean_touch_is_zero_and_jury_is_unchanged(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_event(_snapshot(WINDOW))
    desk.on_event(_trade(WINDOW), [ZONE])
    # +10 that stays: a real add, not a pull. DEFEND for ZLG, CLEAN for ОКО.
    desk.on_event(_diff(WINDOW + timedelta(seconds=2), seq=2, bid="30"))
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    journal = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert journal is not None
    assert journal["oko_label"] == "CLEAN"
    assert journal["oko_book_trust"] == "1.0000"
    assert journal["oko_voice"] == 0
    assert journal["oko_regime"] == "UNKNOWN"
    assert journal["oko_set"] == "bounce|break|die"
    assert journal["oko_n_class"] == 0
    assert journal["zlg_label"] == "DEFEND"
    assert journal["jury"] == "SILENCE"  # n<20 on CAV/ZLG, as before ОКО


def test_no_book_at_the_print_is_unknown_and_zero(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_event(_trade(WINDOW), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    assert desk.state_for("BTCUSDT").oko_window is None
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    journal = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert journal is not None
    assert journal["oko_label"] == "UNKNOWN"
    assert journal["oko_voice"] == 0
    assert journal["oko_fingerprint"] is None
    assert journal["oko_reason"] == "no book at the print"


def test_outcome_teaches_the_immune_memory_and_persists(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _touch_then_wall(desk, wall="45")
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    touch_id = events[0]["touch_id"]
    assert desk.oko.memory_for("BTCUSDT").n == 0
    # Price leaves the zone by ≥ 8 ticks → bounce. Not a trap for a bounce idea.
    away = WINDOW + timedelta(minutes=20)
    desk.on_event(_trade(away, px="102.0", side="buy"), [])
    out = desk.tick(away)
    assert any(e.get("event") == "shadow_outcome" and e["outcome"] == "bounce" for e in out)
    mem = desk.oko.memory_for("BTCUSDT")
    assert mem.n == 1
    assert mem.records[0].trap is False
    journal = desk.knowledge.get_journal_touch(touch_id)
    assert journal is not None and journal["outcome"] == "bounce"
    raw = desk.knowledge.meta("oko:memory:BTCUSDT")
    assert raw is not None and '"trap": false' in raw
    # A new desk on the same knowledge starts with the same organs.
    again = OkoEye(working_tf="15m")
    assert again.load(desk.knowledge) >= 2
    assert again.memory_for("BTCUSDT").n == 1
    assert again.passport_for("BTCUSDT").depth.n == 1


def test_working_bar_feeds_weather_and_is_saved(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    for i in range(3):
        desk.on_bar_close(
            _bar(WINDOW + timedelta(minutes=15 * i), close=str(Decimal("100.6") + Decimal(i) / 10))
        )
    assert desk.oko.weather_for("BTCUSDT").n == 2
    assert desk.knowledge.meta("oko:weather:BTCUSDT") is not None
    reloaded = DeskLoop(knowledge=desk.knowledge, user_mode="off", tick_size=TICK)
    assert reloaded.oko.weather_for("BTCUSDT").n == 2


def test_flatten_drops_the_oko_window(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _touch_then_wall(desk, wall="45")
    desk.tick(WINDOW + timedelta(seconds=8))
    assert desk.state_for("BTCUSDT").oko_window is not None
    desk.on_event({"kind": "flatten", "symbol": "BTCUSDT"})
    assert desk.state_for("BTCUSDT").oko_window is None


def test_two_desks_same_tape_same_oko_journal(tmp_path: Path) -> None:
    def run(name: str) -> dict:
        desk = _desk(tmp_path / name)
        _touch_then_wall(desk, wall="45")
        desk.tick(WINDOW + timedelta(seconds=8))
        events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
        row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
        assert row is not None
        return {k: v for k, v in row.items() if k.startswith("oko_") or k == "jury"}

    assert run("a") == run("b")


def _oi(ts: datetime, oi: str) -> MarketEvent:
    return MarketEvent(
        stream="oi",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"oi": oi},
    )


def _liq(ts: datetime, *, qty: str, position: str) -> MarketEvent:
    return MarketEvent(
        stream="liquidation",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": "100.3", "qty": qty, "position": position},
    )


def test_oi_funding_liquidation_feeds_reach_the_footprint(tmp_path: Path) -> None:
    """OI before the print and inside 8s → ΔOI is a fact in the journal; liquidations too."""
    desk = _desk(tmp_path)
    desk.on_event(_oi(WINDOW - timedelta(seconds=30), "1000000"))
    desk.on_event(
        MarketEvent(
            stream="funding",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW - timedelta(seconds=20),
            recv_ts=WINDOW - timedelta(seconds=20),
            payload={"funding": "0.0001"},
        )
    )
    desk.on_event(_snapshot(WINDOW))
    desk.on_event(_trade(WINDOW), [ZONE])
    desk.on_event(_oi(WINDOW + timedelta(seconds=4), "1010000"))
    desk.on_event(_liq(WINDOW + timedelta(seconds=3), qty="2", position="long"))
    desk.on_event(
        _liq(WINDOW + timedelta(seconds=30), qty="50", position="short")
    )  # after the clock
    desk.on_event(_diff(WINDOW + timedelta(seconds=2), seq=2, bid="30"))
    desk.tick(WINDOW + timedelta(seconds=8))
    st = desk.state_for("BTCUSDT")
    assert st.oko_window is not None
    fr = st.oko_window.frame
    assert (fr.oi_before, fr.oi_after) == (Decimal("1000000"), Decimal("1010000"))
    assert fr.oi_delta_frac == Decimal("0.01")
    assert fr.oi_z is None  # first OI window: the stat is not mature → no BUILD label, honestly
    assert fr.liq_long_qty == Decimal("2") and fr.liq_short_qty == Decimal("0")
    assert fr.funding == Decimal("0.0001")
    assert st.oko_window.footprint.label == "NONE"
    assert desk.oko.passport_for("BTCUSDT").oi_delta_frac.n == 1
    assert desk.oko.passport_for("BTCUSDT").funding.n == 1
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    journal = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert journal is not None
    assert journal["oko_footprint"] == "NONE"
    assert journal["oko_footprint_side"] is None
    assert journal["oko_oi_z"] is None
    assert journal["oko_liq_rel"] is None
    assert journal["oko_fingerprint"].count("-") == 12


def test_bad_feed_rows_are_dropped_not_stored(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_event(_oi(WINDOW, "0"))
    desk.on_event(_oi(WINDOW, "abc"))
    desk.on_event(_liq(WINDOW, qty="0", position="long"))
    desk.on_event(
        MarketEvent(
            stream="liquidation",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            payload={"px": "1", "qty": "1", "position": "buy"},
        )
    )
    st = desk.state_for("BTCUSDT")
    assert st.oi == [] and st.liquidations == []
    desk.on_event(_oi(WINDOW, "5"))
    desk.on_event(_oi(WINDOW + timedelta(hours=3), "6"))
    assert [lv for _, lv in st.oi] == [Decimal("6")]  # 2h retention


def test_liquidation_stream_orders_with_prints(tmp_path: Path) -> None:
    from capitalizator.desk.loop import _ordered_events

    liq = _liq(WINDOW, qty="1", position="long")
    bar = {"kind": "bar_close", "bar": _bar(WINDOW)}
    order = _ordered_events([bar, _trade(WINDOW), liq, _snapshot(WINDOW)])
    kinds = [e.stream if isinstance(e, MarketEvent) else "bar_close" for e in order]
    assert kinds[0] == "snapshot"
    assert kinds[-1] == "bar_close"
    assert set(kinds[1:3]) == {"trades", "liquidation"}


def test_touch_resolved_before_its_jury_is_still_learned_once(tmp_path: Path) -> None:
    """Audit fact: a bounce inside 30s left memory.n == 0 forever. Learn at the jury, once."""
    desk = _desk(tmp_path)
    _touch_then_wall(desk, wall="45")
    desk.tick(WINDOW + timedelta(seconds=8))
    desk.on_event(_trade(WINDOW + timedelta(seconds=30), px="102.0", side="buy"), [])
    out = desk.tick(WINDOW + timedelta(seconds=31))
    assert any(e.get("event") == "shadow_outcome" for e in out)
    assert desk.oko.memory_for("BTCUSDT").n == 0  # idea not stamped yet → settle cannot learn
    desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert desk.oko.memory_for("BTCUSDT").n == 1
    # Later settles do not learn it again.
    desk.tick(WINDOW + timedelta(minutes=20))
    assert desk.oko.memory_for("BTCUSDT").n == 1
    raw = desk.knowledge.meta("oko:memory:BTCUSDT")
    assert raw is not None and raw.count('"trap"') == 1


def test_touch_resolved_after_its_jury_is_learned_once(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _touch_then_wall(desk, wall="45")
    desk.tick(WINDOW + timedelta(seconds=8))
    desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert desk.oko.memory_for("BTCUSDT").n == 0
    desk.on_event(_trade(WINDOW + timedelta(minutes=20), px="102.0", side="buy"), [])
    desk.tick(WINDOW + timedelta(minutes=20))
    assert desk.oko.memory_for("BTCUSDT").n == 1
    desk.tick(WINDOW + timedelta(minutes=25))
    assert desk.oko.memory_for("BTCUSDT").n == 1


def test_b_veto_does_not_blind_oko(tmp_path: Path) -> None:
    """Audit fact: with a B veto the window was never observed (label None, passport 0)."""
    from capitalizator.card.live import CardLive

    desk = _desk(tmp_path)
    veto = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="veto",
        known_at=WINDOW,
        pluses=("calendar_FOMC", "known_at_set", "window_marked"),
        minuses=("fomc_inside_2h", "first_print_unplayed"),
    )
    desk.knowledge.put_card_live("BTCUSDT", veto.to_payload())
    _touch_then_wall(desk, wall="45")
    events = desk.tick(WINDOW + timedelta(seconds=8))
    # D-18 (main): contour B never stops labelling; ОКО observes on the same clock.
    assert events[0]["event"] == "zlg"
    row = next(t for t in desk.registry.touches if t.touch_id == events[0]["touch_id"])
    assert row.oko_label == "SPOOF"
    assert desk.oko.passport_for("BTCUSDT").depth.n == 1
    out = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    journal = desk.knowledge.get_journal_touch(out[0]["touch_id"])
    assert journal is not None
    assert journal["skip_reason"] == "b_veto"  # B is the skip reason the operator sees
    assert journal["oko_label"] == "SPOOF"
    assert journal["oko_book_trust"] == "0.0000"
    assert journal["oko_footprint"] == "NONE"
    assert journal["oko_voice"] == "VETO"  # ОКО judged the same touch
    assert journal["jury"] == "VETO"

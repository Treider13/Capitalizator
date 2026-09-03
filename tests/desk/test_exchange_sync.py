"""Desk ↔ venue truth: equity, failed intents, venue-flat, veto flatten, instruments."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.card.live import CardLive
from capitalizator.desk.loop import DeskLoop
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
SUP = Zone.create(symbol="BTCUSDT", tf="15m", side="support", lo=Decimal("99000"),
                  hi=Decimal("100000.2"), method="prior_day_hl", created_as_of=CREATED)
RES = Zone.create(symbol="ETHUSDT", tf="15m", side="resistance", lo=Decimal("3999.8"),
                  hi=Decimal("4040"), method="prior_day_hl", created_as_of=CREATED)


def _trade(ts: datetime, px: str, symbol: str = "BTCUSDT", side: str = "sell") -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol=symbol, exchange_ts=ts, recv_ts=ts,
                       payload={"px": px, "qty": "1", "side": side})


def _desk(tmp_path: Path, mode: str, zone: Zone, px: str) -> DeskLoop:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode=mode, tick_size=TICK)
    desk.registry._zones[zone.zone_id] = zone
    for i in range(20):
        desk.registry.touches.append(replace(
            Touch.create(zone_id=zone.zone_id, ts=CREATED + timedelta(seconds=i + 1),
                         trade_px=Decimal(px), trade_qty=Decimal("1")),
            outcome="bounce", cav_label="REJECT", gesture="DEFEND", tape_eaten=False, btc_regime="box"))
    desk.btc.regime = "box"
    p = Decimal(px)
    book = Book(tick_size=str(desk.tick_for(zone.symbol)))
    tick = desk.tick_for(zone.symbol)
    if zone.side == "support":
        bids, asks = ((str(p), "20"),), ((str(p + 2 * tick), "20"),)
    else:
        bids, asks = ((str(p - 2 * tick), "20"),), ((str(p), "20"),)
    book.apply_snapshot(BookSnapshot(symbol=zone.symbol, exchange_ts=WINDOW, seq=1, bids=bids, asks=asks))
    desk.on_book(zone.symbol, book)
    return desk


def _arm_and_close(desk: DeskLoop, zone: Zone, px: str, when: datetime = WINDOW) -> dict:
    p = Decimal(px)
    tick = desk.tick_for(zone.symbol)
    taker = "sell" if zone.side == "support" else "buy"
    desk.on_trade(_trade(when, px, zone.symbol, taker), [zone])
    live = desk.state_for(zone.symbol).last_touch
    add_side = "b" if zone.side == "support" else "a"
    book = desk.state_for(zone.symbol).book
    bigger = book.level("bid" if add_side == "b" else "ask", str(p)) + 45  # a real add, not a cut
    desk.on_event(MarketEvent(stream="book_diff", exchange="bybit", symbol=zone.symbol,
                              exchange_ts=when + timedelta(seconds=2), recv_ts=when + timedelta(seconds=2),
                              seq=book.seq + 1,
                              payload={add_side: [[str(p), str(bigger)]], ("a" if add_side == "b" else "b"): []}))
    desk.registry._patch(touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED")
    desk.tick(when + timedelta(seconds=8))
    if zone.side == "support":
        bar = Bar(symbol=zone.symbol, tf="15m", open_ts=when - timedelta(minutes=10),
                  close_ts=when + timedelta(minutes=5), open=p, high=p + 3 * tick,
                  low=zone.lo - 10, close=zone.hi)
    else:
        bar = Bar(symbol=zone.symbol, tf="15m", open_ts=when - timedelta(minutes=10),
                  close_ts=when + timedelta(minutes=5), open=p, low=p - 3 * tick,
                  high=zone.hi + 10, close=zone.lo)
    return desk.on_bar_close(bar)[0]


def test_short_spring_at_resistance_sends_sell_and_paper_twin_mirrors_it(tmp_path: Path) -> None:
    """We trade both ways: a spring at RESISTANCE is a SELL with the stop above the wick."""
    desk = _desk(tmp_path, "demo", RES, "4000")
    ev = _arm_and_close(desk, RES, "4000")
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert row["idea"] == "spring" and row["idea_side"] == "sell", row.get("send_skip")
    assert ev["sent"] is True, row.get("send_skip")
    intent = desk.knowledge.pending_intents()[0]["payload"]
    assert intent["side"] == "sell"
    assert Decimal(intent["stop"]) > Decimal(intent["entry"]) > Decimal(intent["tp"])
    assert Decimal(intent["structural"]) >= Decimal("4050")  # behind the wick high 4050 + buffer
    twin = desk.paper.positions[row["paper_ids"]["demo"]]
    assert twin.side == "sell" and twin.stop > twin.limit_px
    # fade challenger is the opposite (buy) and shadow is sell too
    assert desk.paper.positions[row["paper_ids"]["fade"]].side == "buy"
    assert desk.paper.positions[row["paper_ids"]["shadow"]].side == "sell"
    # short fills when a buyer lifts our ask; +1R is DOWN
    t = WINDOW + timedelta(minutes=6)
    desk.on_trade(_trade(t, "4000", "ETHUSDT", "buy"), [RES])
    assert twin.state == "open"
    desk.on_trade(_trade(t + timedelta(minutes=1), str(Decimal("4000") - twin.r_px - 1), "ETHUSDT"), [RES])
    assert twin.half_taken and twin.half_px < twin.entry_px
    oms = desk.knowledge.oms_rows()
    half = next(c for c in oms if c["kind"] == "half_tp")
    assert half["payload"]["side"] == "sell" and Decimal(half["payload"]["price"]) < Decimal("4000")


def test_exchange_equity_drives_account_and_halts_in_live(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "live", SUP, "100000.1")
    assert desk.account.equity_source == "paper"
    desk.knowledge.set_meta("exchange_state", json.dumps({
        "at": WINDOW.isoformat(), "mode": "live_sub", "equity": "50000", "positions": [], "mismatches": []}))
    out = desk.tick(WINDOW + timedelta(seconds=1))
    assert {"event": "equity", "equity": "50000", "source": "live"} in out
    assert desk.account.equity == Decimal("50000") and desk.account.equity_source == "exchange:live"
    # halts read the real equity: −4% day → day halt
    desk.knowledge.set_meta("exchange_state", json.dumps({
        "at": (WINDOW + timedelta(seconds=2)).isoformat(), "equity": "48000", "positions": []}))
    desk.tick(WINDOW + timedelta(seconds=3))
    assert desk.account.halts.halted and desk.account.halts.reason == "day"
    # stale state (> 5 min) is ignored
    desk.knowledge.set_meta("exchange_state", json.dumps({
        "at": (WINDOW - timedelta(minutes=10)).isoformat(), "equity": "1", "positions": []}))
    desk.tick(WINDOW + timedelta(seconds=4))
    assert desk.account.equity == Decimal("48000")
    # off mode never touches the account
    desk.user_mode = "off"
    desk.knowledge.set_meta("exchange_state", json.dumps({
        "at": (WINDOW + timedelta(seconds=5)).isoformat(), "equity": "77", "positions": []}))
    desk.tick(WINDOW + timedelta(seconds=6))
    assert desk.account.equity == Decimal("48000")


def test_failed_intent_frees_the_idea_and_venue_flat_closes_twin(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP, "100000.1")
    ev = _arm_and_close(desk, SUP, "100000.1")
    assert ev["sent"] is True
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert "BTCUSDT" in desk.account.open
    # signer says the venue refused it → idea freed, twin closed, journal keeps the reason
    desk.knowledge.mark_intent(row["intent_id"], "failed")
    out = desk.tick(WINDOW + timedelta(minutes=6))
    assert {"event": "idea_freed", "symbol": "BTCUSDT", "reason": "intent_failed"} in out
    assert desk.account.open == {} and desk.risk.allow_entry("BTCUSDT")
    twin = next(p for p in desk.paper.closed if p.paper_id == row["paper_ids"]["demo"])
    assert twin.exit_reason == "intent_failed" and twin.entry_px is None
    # second idea: filled twin, then the venue reports flat after the grace → twin closed
    desk.registry.touches = [t for t in desk.registry.touches if t.outcome != "pending"]
    w2 = WINDOW + timedelta(minutes=20)
    ev2 = _arm_and_close(desk, SUP, "100000.1", when=w2)
    assert ev2["sent"] is True, desk.knowledge.get_journal_touch(ev2["touch_id"]).get("send_skip")
    row2 = desk.knowledge.get_journal_touch(ev2["touch_id"])
    twin2 = desk.paper.positions[row2["paper_ids"]["demo"]]
    t = w2 + timedelta(minutes=6)
    desk.on_trade(_trade(t, "100000.1"), [SUP])
    assert twin2.state == "open"
    fresh = t + timedelta(seconds=30)
    desk.knowledge.set_meta("exchange_state", json.dumps({"at": fresh.isoformat(), "positions": []}))
    desk.tick(fresh)
    assert twin2.state == "open"  # inside the 90 s grace: the venue may not have filled yet
    later = t + timedelta(seconds=120)
    desk.knowledge.set_meta("exchange_state", json.dumps({"at": later.isoformat(), "positions": []}))
    out = desk.tick(later)
    assert {"event": "venue_flat", "symbol": "BTCUSDT"} in out
    assert twin2.state == "closed" and twin2.exit_reason == "venue_flat"
    assert desk.account.open == {}


def test_b_veto_flattens_the_live_twin_and_queues_venue_flatten(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP, "100000.1")
    ev = _arm_and_close(desk, SUP, "100000.1")
    assert ev["sent"] is True
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    twin = desk.paper.positions[row["paper_ids"]["demo"]]
    desk.on_trade(_trade(WINDOW + timedelta(minutes=6), "100000.1"), [SUP])
    assert twin.state == "open"
    veto = CardLive(symbol="BTCUSDT", bearing_verdict="veto", known_at=WINDOW + timedelta(minutes=20),
                    pluses=("calendar_FOMC", "known_at_set", "window_marked"),
                    minuses=("fomc_inside_2h", "first_print_unplayed"))
    desk.knowledge.put_card_live("BTCUSDT", veto.to_payload())
    desk.registry.touches = [t for t in desk.registry.touches if t.outcome != "pending"]
    desk.on_trade(_trade(WINDOW + timedelta(minutes=20), "100000.1"), [SUP])
    desk.tick(WINDOW + timedelta(minutes=20, seconds=8))
    bar = Bar(symbol="BTCUSDT", tf="15m", open_ts=WINDOW + timedelta(minutes=20),
              close_ts=WINDOW + timedelta(minutes=35), open=Decimal("100000.1"), high=Decimal("100000.4"),
              low=Decimal("98990"), close=Decimal("100000.2"))
    out = desk.on_bar_close(bar)
    assert out[0]["jury"] == "VETO" and out[0]["action"] == "flatten"
    assert twin.state == "closed" and twin.exit_reason == "b_veto"
    assert any(c["kind"] == "flatten" and c["payload"]["reason"] == "b_veto" for c in desk.knowledge.oms_rows())
    assert desk.account.open == {}


def test_venue_equity_is_not_double_counted_and_twin_exit_flattens_venue(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "live", SUP, "100000.1")
    desk.knowledge.set_meta("exchange_state", json.dumps({
        "at": WINDOW.isoformat(), "equity": "80000", "positions": [], "mismatches": []}))
    desk.tick(WINDOW - timedelta(seconds=1))
    assert desk.account.equity == Decimal("80000") and desk.account.equity_source == "exchange:live"
    # the first wallet reading re-baselines the halts: 80 000 vs paper 100 000 is not a −20% day
    assert not desk.account.halts.halted and desk.account.halts.day_start == Decimal("80000")
    ev = _arm_and_close(desk, SUP, "100000.1")
    assert ev["sent"] is True, desk.knowledge.get_journal_touch(ev["touch_id"]).get("send_skip")
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    twin = desk.paper.positions[row["paper_ids"]["demo"]]
    t = WINDOW + timedelta(minutes=6)
    desk.on_trade(_trade(t, "100000.1"), [SUP])
    desk.on_trade(_trade(t + timedelta(minutes=1), str(twin.stop - 1)), [SUP])
    assert twin.state == "closed" and twin.exit_reason == "stop"
    # paper loss is NOT subtracted again: the venue wallet already carries it
    assert desk.account.equity == Decimal("80000")
    assert desk.account.open == {}
    # and the venue is told to follow the desk's exit (cancel entries + close leftovers)
    flat = [c for c in desk.knowledge.oms_rows() if c["kind"] == "flatten"]
    assert flat and flat[0]["payload"]["reason"] == "twin_stop" and flat[0]["symbol"] == "BTCUSDT"
    # paper account (no venue) still moves on paper P&L
    desk2 = _desk(tmp_path / "paper", "demo", SUP, "100000.1")
    ev2 = _arm_and_close(desk2, SUP, "100000.1")
    row2 = desk2.knowledge.get_journal_touch(ev2["touch_id"])
    twin2 = desk2.paper.positions[row2["paper_ids"]["demo"]]
    desk2.on_trade(_trade(t, "100000.1"), [SUP])
    desk2.on_trade(_trade(t + timedelta(minutes=1), str(twin2.stop - 1)), [SUP])
    assert desk2.account.equity < desk2.risk_config.paper_equity


def test_refuted_class_is_not_sent_but_still_shadowed(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP, "100000.1")
    # 40 filled shadow losers of the exact class this touch will produce (spring × REJECT × DEFEND)
    for i in range(40):
        desk.knowledge.put_paper_trade({
            "paper_id": f"old{i}:shadow", "touch_id": f"old{i}", "source": "shadow", "symbol": "BTCUSDT",
            "closed_at": (CREATED + timedelta(minutes=i)).isoformat(), "tag": "spring",
            "entry_px": "100", "r_net": "-1.2", "realized": "-1", "fees": "0.1", "funding": "0",
            "labels": {"cav_label": "REJECT", "zlg_label": "DEFEND"},
        })
    desk.tick(WINDOW - timedelta(minutes=1))  # refresh calibration
    ev = _arm_and_close(desk, SUP, "100000.1")
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert row["jury"] == "ACCORD" and row["idea"] == "spring"
    assert ev["sent"] is False
    assert row["send_skip"].startswith("calib:spring|REJECT|DEFEND")
    assert row["calibration"]["n"] == 40 and Decimal(row["calibration"]["upper"]) < Decimal("0.2")
    assert desk.knowledge.pending_intents() == []
    # the shadow and the fade keep trading on paper — the verdict can flip with data
    assert set(row["paper_ids"]) == {"shadow", "fade"}
    # rows without a window label feed the legacy aggregate `idea|cav|zlg|*|*`
    assert json.loads(desk.knowledge.meta("calibration"))["spring|REJECT|DEFEND|*|*"]["n"] == 40


def test_instruments_published_by_signer_are_loaded_by_desk(tmp_path: Path) -> None:
    from capitalizator.instruments import InstrumentRegistry, instrument_from_bybit

    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    desk = DeskLoop(knowledge=kn, user_mode="off")
    assert not desk.instrument_ok("DOGEUSDT") and "DOGEUSDT" in desk.refused_symbols
    reg = InstrumentRegistry()
    reg.put(instrument_from_bybit({
        "symbol": "DOGEUSDT", "status": "Trading",
        "priceFilter": {"tickSize": "0.00001"},
        "lotSizeFilter": {"qtyStep": "1", "minOrderQty": "1", "minNotionalValue": "5"},
        "leverageFilter": {"maxLeverage": "75"}, "fundingInterval": 480,
    }, fetched_at=WINDOW))
    kn.set_meta("instruments_snapshot", json.dumps(reg.to_snapshot()))
    desk.tick(WINDOW)
    assert desk.instruments.tick("DOGEUSDT") == Decimal("0.00001")
    assert "DOGEUSDT" not in desk.refused_symbols and desk.instrument_ok("DOGEUSDT")
    # a fresh desk picks the snapshot up at start
    desk2 = DeskLoop(knowledge=kn, user_mode="off")
    assert desk2.instruments.has("DOGEUSDT")

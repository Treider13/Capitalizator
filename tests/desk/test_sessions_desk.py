"""Sessions release: the desk sends by UTC window, sizes and stops by window, journals
the verdict, and the 24/7 paper twins carry the window labels the calibrator needs."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.book.reconstruct import Book
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
OVERLAP = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)  # Monday, overlap window
NIGHT = datetime(2026, 8, 31, 22, 10, tzinfo=UTC)
ASIA = datetime(2026, 9, 1, 3, 10, tzinfo=UTC)  # Tuesday, asia + thin-alts blackout
ASIA_LATE = datetime(2026, 9, 1, 6, 30, tzinfo=UTC)  # asia, after the 02–06 blackout
SATURDAY = datetime(2026, 9, 5, 14, 10, tzinfo=UTC)


def _zone(symbol: str, lo: str, hi: str) -> Zone:
    return Zone.create(symbol=symbol, tf="15m", side="support", lo=Decimal(lo), hi=Decimal(hi),
                       method="prior_day_hl", created_as_of=CREATED)


SUP_BTC = _zone("BTCUSDT", "99000", "100000.2")
SUP_ETH = _zone("ETHUSDT", "3900", "4000.2")
SUP_SOL = _zone("SOLUSDT", "190", "200.2")


def _trade(ts: datetime, px: str, symbol: str, side: str = "sell") -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol=symbol, exchange_ts=ts, recv_ts=ts,
                       payload={"px": px, "qty": "1", "side": side})


def _desk(tmp_path: Path, mode: str, zone: Zone, px: str, when: datetime) -> DeskLoop:
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
    book.apply_snapshot(BookSnapshot(symbol=zone.symbol, exchange_ts=when, seq=1,
                                     bids=((str(p), "20"),), asks=((str(p + 2 * tick), "20"),)))
    desk.on_book(zone.symbol, book)
    return desk


def _arm_and_close(desk: DeskLoop, zone: Zone, px: str, when: datetime) -> dict:
    p = Decimal(px)
    tick = desk.tick_for(zone.symbol)
    desk.on_trade(_trade(when, px, zone.symbol, "sell"), [zone])
    live = desk.state_for(zone.symbol).last_touch
    book = desk.state_for(zone.symbol).book
    bigger = book.level("bid", str(p)) + 45
    desk.on_event(MarketEvent(stream="book_diff", exchange="bybit", symbol=zone.symbol,
                              exchange_ts=when + timedelta(seconds=2), recv_ts=when + timedelta(seconds=2),
                              seq=book.seq + 1, payload={"b": [[str(p), str(bigger)]], "a": []}))
    desk.registry._patch(touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED")
    desk.tick(when + timedelta(seconds=8))
    bar = Bar(symbol=zone.symbol, tf="15m", open_ts=when - timedelta(minutes=10),
              close_ts=when + timedelta(minutes=5), open=p, high=p + 3 * tick,
              low=zone.lo - 10, close=zone.hi)
    return desk.on_bar_close(bar)[0]


def test_overlap_sends_full_size_and_journals_the_window(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", OVERLAP)
    ev = _arm_and_close(desk, SUP_BTC, "100000.1", OVERLAP)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert ev["sent"] is True, row.get("send_skip")
    assert row["session_window"] == "overlap" and row["session_weekend"] is False
    assert row["session_gate"] == "window:overlap"
    assert row["session_size_mult"] == "1.0" and row["session_k_atr"] == "0.5"
    assert row["size_mult_applied"] == "1"
    assert row["session_name"] == "overlap"
    twin = desk.paper.positions[row["paper_ids"]["demo"]]
    assert twin.labels["window"] == "overlap" and twin.labels["symbol_group"] == "majors"
    assert twin.labels["k_atr"] == "0.5" and twin.labels["size_mult"] == "1.0"
    assert twin.stop_components["k_atr"] == "0.5"
    shadow = desk.paper.positions[row["paper_ids"]["shadow"]]
    assert shadow.labels["window"] == "overlap"
    assert desk.account.budget(OVERLAP, key="2026-08-31:overlap", max_n=8).n == 1


def test_night_does_not_send_but_the_shadow_still_trades(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", NIGHT)
    ev = _arm_and_close(desk, SUP_BTC, "100000.1", NIGHT)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert row["jury"] == "ACCORD"
    assert ev["sent"] is False
    assert row["session_window"] == "night" and row["session_gate"] == "window:night:closed"
    assert desk.knowledge.pending_intents() == []
    assert set(row["paper_ids"]) == {"shadow", "fade"}
    assert desk.paper.positions[row["paper_ids"]["shadow"]].labels["window"] == "night"
    # night uses the wider buffer on the paper twin
    assert desk.paper.positions[row["paper_ids"]["shadow"]].stop_components["k_atr"] == "0.8"


def test_asia_cuts_size_in_half_for_majors(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_ETH, "4000.1", ASIA_LATE)
    ev = _arm_and_close(desk, SUP_ETH, "4000.1", ASIA_LATE)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert ev["sent"] is True, row.get("send_skip")
    assert row["session_window"] == "asia" and row["size_mult_applied"] == "0.5"
    intent = desk.knowledge.pending_intents()[0]["payload"]
    full = row["sizing"]["qty"]
    assert Decimal(intent["qty"]) <= Decimal(full) * Decimal("0.5")


def test_asia_thin_hours_refuse_an_alt(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_SOL, "200.1", ASIA)
    desk.turnover["SOLUSDT"] = Decimal("5e9")  # rank 1 → top5 policy would pass
    ev = _arm_and_close(desk, SUP_SOL, "200.1", ASIA)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert ev["sent"] is False
    assert row["session_gate"] == "blackout:asia_thin_alts"
    assert desk.paper.positions[row["paper_ids"]["shadow"]].labels["symbol_group"] == "top10"


def test_asia_refuses_an_unranked_alt_and_passes_a_ranked_one(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_SOL, "200.1", ASIA_LATE)
    ev = _arm_and_close(desk, SUP_SOL, "200.1", ASIA_LATE)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert ev["sent"] is False and row["session_gate"] == "window:asia:symbols:not_top5"


def test_funding_settlement_blackout(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", OVERLAP)
    desk.on_event(MarketEvent(
        stream="funding", exchange="bybit", symbol="BTCUSDT", exchange_ts=OVERLAP, recv_ts=OVERLAP,
        payload={"funding": "0.0001",
                 "next_funding_ts": str(int((OVERLAP + timedelta(minutes=8)).timestamp() * 1000)),
                 "interval_min": "60", "turnover24h": "12345678.9"},
    ))
    assert desk.next_funding["BTCUSDT"] == OVERLAP + timedelta(minutes=8)
    assert desk.turnover["BTCUSDT"] == Decimal("12345678.9")
    # the bar closes at +5 min → 3 min before settlement → blackout
    ev = _arm_and_close(desk, SUP_BTC, "100000.1", OVERLAP)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert ev["sent"] is False and row["session_gate"] == "funding_settlement"


def test_ticker_interval_overrides_instruments_info(tmp_path: Path) -> None:
    from capitalizator.instruments import InstrumentRegistry, instrument_from_bybit

    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    reg = InstrumentRegistry()
    reg.put(instrument_from_bybit({
        "symbol": "DOGEUSDT", "status": "Trading", "priceFilter": {"tickSize": "0.00001"},
        "lotSizeFilter": {"qtyStep": "1", "minOrderQty": "1", "minNotionalValue": "5"},
        "leverageFilter": {"maxLeverage": "75"}, "fundingInterval": 480,
    }, fetched_at=OVERLAP))
    kn.set_meta("instruments_snapshot", json.dumps(reg.to_snapshot()))
    desk = DeskLoop(knowledge=kn, user_mode="off")
    assert desk.instruments.get("DOGEUSDT").funding_interval_min == 480
    desk.on_event(MarketEvent(stream="funding", exchange="bybit", symbol="DOGEUSDT",
                              exchange_ts=OVERLAP, recv_ts=OVERLAP,
                              payload={"funding": "0.005", "interval_min": "60"}))
    assert desk.instruments.get("DOGEUSDT").funding_interval_min == 60
    assert desk.instruments.get("DOGEUSDT").source == "ticker"


def test_universe_rank_orders_by_turnover(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off",
                    tick_size=TICK)
    assert desk.universe_rank() is None
    desk.turnover.update({"BTCUSDT": Decimal("10"), "SOLUSDT": Decimal("3"), "XRPUSDT": Decimal("5")})
    assert desk.universe_rank() == {"BTCUSDT": 1, "XRPUSDT": 2, "SOLUSDT": 3}
    assert desk.symbol_group("SOLUSDT", desk.universe_rank()) == "top10"
    assert desk.symbol_group("TIAUSDT", desk.universe_rank()) == "rest"
    assert desk.symbol_group("ETHUSDT", None) == "majors"


def test_weekend_sends_majors_at_half_size_and_refuses_alts(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", SATURDAY)
    ev = _arm_and_close(desk, SUP_BTC, "100000.1", SATURDAY)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert ev["sent"] is True, row.get("send_skip")
    assert row["session_window"] == "weekend" and row["session_weekend"] is True
    assert row["session_name"] == "overlap"  # clock label stays; weekend is the flag
    assert row["size_mult_applied"] == "0.5"
    desk2 = _desk(tmp_path / "b", "demo", SUP_SOL, "200.1", SATURDAY)
    desk2.turnover["SOLUSDT"] = Decimal("5e9")
    ev2 = _arm_and_close(desk2, SUP_SOL, "200.1", SATURDAY)
    row2 = desk2.knowledge.get_journal_touch(ev2["touch_id"])
    assert ev2["sent"] is False and row2["session_gate"] == "window:weekend:symbols:majors_only"


def test_second_idea_in_the_same_correlation_group_is_refused(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", OVERLAP)
    ev = _arm_and_close(desk, SUP_BTC, "100000.1", OVERLAP)
    assert ev["sent"] is True
    assert desk.account.allow_entry("ETHUSDT") == (False, "corr:BTCUSDT:group:majors")
    assert desk.account.allow_entry("SOLUSDT") == (True, "ok")
    assert desk.account.allow_entry("BTCUSDT") == (False, "position_open_same_symbol")


def test_window_drift_halves_size_until_released(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", OVERLAP)
    # 30 winners then 30 losers in the overlap window: the loss rate rose → drift
    for i in range(60):
        r = "1" if i < 30 else "-1"
        for tag in ("bounce", "spring"):
            desk.knowledge.put_paper_trade({
                "paper_id": f"o{i}{tag}:shadow", "touch_id": f"o{i}{tag}", "source": "shadow",
                "symbol": "BTCUSDT",
                "closed_at": (OVERLAP - timedelta(days=3) + timedelta(minutes=i)).isoformat(),
                "tag": tag, "entry_px": "100", "r_net": r, "realized": r, "fees": "0",
                "funding": "0", "hold_s": str(3600 * 4), "mae_px": "99.7",
                "labels": {"cav_label": "REJECT", "zlg_label": "DEFEND", "window": "overlap",
                           "symbol_group": "majors", "atr": "1"},
            })
    desk.tick(OVERLAP - timedelta(minutes=1))
    assert "overlap" in desk._window_drift
    window = desk.policy.window(OVERLAP)
    assert desk.window_size_mult(window) == Decimal("0.5")
    assert desk.hold_hours_for("bounce", window) == Decimal(4)
    assert json.loads(desk.knowledge.meta("window_drift")) == desk._window_drift
    ev = _arm_and_close(desk, SUP_BTC, "100000.1", OVERLAP)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    # this class is 50/50 over 60 → not refuted; the drift cut shows in the size
    if ev["sent"]:
        assert Decimal(row["size_mult_applied"]) == Decimal("0.5")
        assert Decimal(row["ev"]["hold_hours"]) == Decimal(4)
    # the flag survives a desk restart
    desk_b = DeskLoop(knowledge=desk.knowledge, user_mode="demo", tick_size=TICK)
    assert "overlap" in desk_b._window_drift
    desk.knowledge.enqueue_command(
        "drift_release", {"kind": "drift_release", "symbol": "ALL"},
        created_ts="2026-01-05T12:00:00+00:00",
    )
    out = desk.tick(OVERLAP + timedelta(seconds=10))
    assert {"event": "drift_release", "windows": ["overlap"]} in out
    assert desk._window_drift == {} and desk.window_size_mult(window) == Decimal("1.0")
    # the release is remembered: the same old losses do not re-flag on the next refresh
    assert desk._drift_ack_n["overlap"] == 120
    desk._calibration_at = None
    desk.tick(OVERLAP + timedelta(minutes=11))
    assert desk._window_drift == {}
    assert json.loads(desk.knowledge.meta("window_drift_state"))["ack_n"] == {"overlap": 120}
    desk_c = DeskLoop(knowledge=desk.knowledge, user_mode="demo", tick_size=TICK)
    assert desk_c._window_drift == {} and desk_c._drift_ack_n == {"overlap": 120}


def test_command_queue_is_one_table_with_claims(tmp_path: Path) -> None:
    """One queue for console → desk/signer: rows are claimed atomically, never popped
    from a JSON blob; a corrupt meta value cannot exist because there is none."""
    kn = open_knowledge(init_vault(tmp_path / "v"))
    assert kn.claim_commands() == []
    ts = "2026-01-05T12:00:00+00:00"
    assert kn.enqueue_command("pause_entries", {"kind": "pause_entries"}, created_ts=ts) == 1
    assert kn.enqueue_command("resume_entries", {"kind": "resume_entries"}, created_ts=ts) == 2
    got = kn.claim_commands(("pause_entries", "resume_entries"))
    assert [c["kind"] for c in got] == ["pause_entries", "resume_entries"]
    assert kn.claim_commands() == []  # claimed rows are not handed out twice
    assert {c["status"] for c in kn.commands(limit=10)} == {"claimed"}
    with pytest.raises(ValueError, match="unknown command kind"):
        kn.enqueue_command("withdraw_all", {"kind": "withdraw_all"}, created_ts=ts)
    kn.close()


def test_risk_config_reload_toggles_the_correlation_guard(tmp_path: Path) -> None:
    from capitalizator.risk.config import RiskConfig, save_risk_config

    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", OVERLAP)
    assert desk.account.correlation is not None
    save_risk_config(desk.knowledge, RiskConfig(max_open_positions=1), ack=True)
    desk.tick(OVERLAP)
    assert desk.account.correlation is None and desk.risk.max_open == 1
    save_risk_config(
        desk.knowledge,
        RiskConfig(max_open_positions=2, corr_block_threshold=Decimal("0.9")),
        ack=True,
    )
    desk.tick(OVERLAP + timedelta(seconds=1))
    assert desk.account.correlation is not None
    assert desk.account.correlation.threshold == Decimal("0.9")


def test_live_funding_interval_survives_an_instruments_merge(tmp_path: Path) -> None:
    from capitalizator.instruments import InstrumentRegistry, instrument_from_bybit

    kn = open_knowledge(init_vault(tmp_path / "v"))
    reg = InstrumentRegistry()
    row = {"symbol": "DOGEUSDT", "status": "Trading", "priceFilter": {"tickSize": "0.00001"},
           "lotSizeFilter": {"qtyStep": "1", "minOrderQty": "1", "minNotionalValue": "5"},
           "leverageFilter": {"maxLeverage": "75"}, "fundingInterval": 480}
    reg.put(instrument_from_bybit(row, fetched_at=OVERLAP))
    kn.set_meta("instruments_snapshot", json.dumps(reg.to_snapshot()))
    desk = DeskLoop(knowledge=kn, user_mode="off")
    desk.on_event(MarketEvent(stream="funding", exchange="bybit", symbol="DOGEUSDT",
                              exchange_ts=OVERLAP, recv_ts=OVERLAP,
                              payload={"funding": "0.005", "interval_min": "60"}))
    assert desk.instruments.get("DOGEUSDT").funding_interval_min == 60
    # the signer republishes instruments-info (still 480) → the live value is kept
    reg2 = InstrumentRegistry()
    reg2.put(instrument_from_bybit(row, fetched_at=OVERLAP + timedelta(hours=1)))
    kn.set_meta("instruments_snapshot", json.dumps(reg2.to_snapshot()))
    desk.tick(OVERLAP + timedelta(hours=1))
    assert desk.instruments.get("DOGEUSDT").funding_interval_min == 60


def test_liquidation_clusters_need_twenty_rows_then_bucket_by_volume(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo", SUP_BTC, "100000.1", OVERLAP)
    st = desk.state_for("BTCUSDT")
    assert desk.liquidation_levels(st, OVERLAP) == ()
    for i in range(25):
        px = "98999.7" if i < 20 else str(Decimal("99500") + i)
        desk.on_event(MarketEvent(stream="liquidation", exchange="bybit", symbol="BTCUSDT",
                                  exchange_ts=OVERLAP - timedelta(minutes=30 - i),
                                  recv_ts=OVERLAP, payload={"px": px, "qty": "2", "position": "long"}))
    levels = desk.liquidation_levels(st, OVERLAP)
    # 20 rows on one 5-tick bucket dominate; p90 of six buckets keeps at most two
    assert Decimal("98999.5") in levels and len(levels) <= 2

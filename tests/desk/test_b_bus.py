"""B bus: put_card_live, freshness, POC, hold-before-ZLG, journal card_id."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.card.live import CardLive, VolumeSnapshot, card_is_fresh
from capitalizator.desk.__main__ import run_once
from capitalizator.desk.loop import DeskLoop
from capitalizator.desk.tape import zones_for_trade
from capitalizator.news_macro.ingest import load_desk_calendar
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _desk(tmp_path: Path, **kwargs: object) -> DeskLoop:
    vault = init_vault(tmp_path / "desk")
    return DeskLoop(knowledge=open_knowledge(vault), tick_size=TICK, **kwargs)  # type: ignore[arg-type]


def _green(*, known_at: datetime = NOW, symbol: str = "BTCUSDT") -> CardLive:
    return CardLive(
        symbol=symbol,
        bearing_verdict="propose",
        known_at=known_at,
        fib_zone="OTE",
        fib_level="0.718",
        rsi_htf="58.40",
        fvg_status="filled",
        sweep_status="done",
        ob_status="bull",
        bos_status="bull",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
        volume=VolumeSnapshot(poc="100.4", vah="101", val="99.5", rvol="2.3"),
    )


def _trade(ts: datetime = NOW) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": "100.5", "qty": "1", "side": "sell"},
    )


def _bar(close_ts: datetime) -> Bar:
    """First closed working bar after the print: wick below the zone, close inside."""
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=close_ts - timedelta(minutes=15),
        close_ts=close_ts,
        open=Decimal("100.5"),
        high=Decimal("101"),
        low=Decimal("99.9"),
        close=Decimal("100.6"),
        volume=Decimal("5"),
    )


def test_load_desk_calendar_reads_repo_macro() -> None:
    rows = load_desk_calendar()
    assert rows
    assert any(row.event_class in {"CPI", "FOMC", "NFP", "PCE"} for row in rows)


def test_run_once_attaches_macro_calendar(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "once")
    kn = open_knowledge(vault)
    desk = run_once(vault=vault, knowledge=kn, now=NOW)
    assert desk.calendar == load_desk_calendar()
    kn.close()


def test_htf_close_writes_b_card(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    bar = Bar(
        symbol="BTCUSDT",
        tf="4h",
        open_ts=NOW,
        close_ts=NOW + timedelta(hours=4),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
    )
    desk.on_bar_close(bar)
    raw = desk.knowledge.get_card_live("BTCUSDT")
    assert raw is not None
    card = CardLive.from_payload(raw)
    assert card.symbol == "BTCUSDT"
    assert card.volume.poc
    assert card.gex_bg is None


def test_stale_card_is_not_used(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    old = _green(known_at=NOW - timedelta(seconds=61))
    desk.knowledge.put_card_live("BTCUSDT", old.to_payload())
    assert card_is_fresh(old, symbol="BTCUSDT", now=NOW) is False
    assert desk._card_for("BTCUSDT", NOW) is None


def test_wrong_symbol_card_is_not_used(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    other = _green(symbol="ETHUSDT")
    desk.knowledge.put_card_live("BTCUSDT", other.to_payload())
    assert desk._card_for("BTCUSDT", NOW) is None


def test_fresh_card_is_used(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    card = _green()
    desk.knowledge.put_card_live("BTCUSDT", card.to_payload())
    got = desk._card_for("BTCUSDT", NOW)
    assert got is not None
    assert got.card_id == card.card_id
    assert got.volume.poc == "100.4"


def test_zones_for_trade_use_card_poc(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    when = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    desk.knowledge.put_card_live("BTCUSDT", _green(known_at=when).to_payload())
    day = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 29, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 29, 16, 15, tzinfo=UTC),
        open=Decimal("95"),
        high=Decimal("100"),
        low=Decimal("90"),
        close=Decimal("98"),
        volume=Decimal("10"),
    )
    desk.state_for("BTCUSDT").bars.append(day)
    zones = zones_for_trade(desk, _trade(when))
    pocs = [z for z in zones if z.method == "vp_hyp"]
    assert pocs
    assert any(z.lo == Decimal("100.4") or z.hi == Decimal("100.4") for z in pocs)


def test_veto_stops_zlg(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    veto = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="veto",
        known_at=NOW,
        pluses=("calendar_FOMC", "known_at_set", "window_marked"),
        minuses=("fomc_inside_2h", "first_print_unplayed"),
    )
    desk.knowledge.put_card_live("BTCUSDT", veto.to_payload())
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=NOW,
            seq=1,
            bids=(("100.4", "20"),),
            asks=(("100.6", "20"),),
        )
    )
    desk.on_book("BTCUSDT", book)
    desk.on_trade(_trade(), [ZONE])
    events = desk.tick(NOW + timedelta(seconds=8))
    assert events
    # D-18: veto no longer stops ZLG — the gesture is stamped for the shadow.
    assert events[0]["event"] == "zlg"
    assert events[0]["gesture"] is not None
    assert desk.state_for("BTCUSDT").state == "LABEL_ZLG"
    closed = desk.on_bar_close(_bar(NOW + timedelta(minutes=15)))
    assert closed[0]["jury"] == "VETO"
    assert closed[0]["sent"] is False
    assert closed[0]["skip_reason"] == "b_veto"
    assert closed[0]["action"] == "flatten"  # 3.14.3 kept: veto flattens an open idea
    assert desk.state_for("BTCUSDT").last_touch is None
    row = desk.knowledge.get_journal_touch(closed[0]["touch_id"])
    assert row["shadow_would"] is False and row["b_gate"] == "b_veto"
    assert row["zlg_label"] is not None and row["cav_label"] is not None


def test_hold_early_return_skips_cav(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    hold = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="hold",
        known_at=NOW,
        pluses=("listing_seen", "official_calendar", "listing_base_rate_low"),
        minuses=("not_in_universe", "no_spot_ack"),
    )
    desk.knowledge.put_card_live("BTCUSDT", hold.to_payload())
    desk.on_book(
        "BTCUSDT",
        Book(tick_size="0.1"),
    )
    desk.registry._zones[ZONE.zone_id] = ZONE
    desk.on_trade(_trade(), [ZONE])
    # D-18: hold no longer short-circuits the labels; it is a skip reason.
    events = desk.tick(NOW + timedelta(seconds=8))
    assert events[0]["event"] == "zlg"
    closed = desk.on_bar_close(_bar(NOW + timedelta(minutes=15)))
    # No book → gesture SILENCE → ZLG voice VETO (existing law); B adds the skip reason.
    assert closed[0]["jury"] == "VETO"
    assert closed[0]["sent"] is False
    assert closed[0]["skip_reason"] == "b_hold"
    row = desk.knowledge.get_journal_touch(closed[0]["touch_id"])
    assert row["zlg_label"] is not None
    assert row["cav_label"] is not None
    assert row["shadow_would"] is False


def test_journal_keeps_b_card_id_and_smc(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    card = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="none",
        ob_status="bull",
        bos_status="bull",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
        volume=VolumeSnapshot(poc="100.4"),
    )
    desk.knowledge.put_card_live("BTCUSDT", card.to_payload())
    desk.registry._zones[ZONE.zone_id] = ZONE
    desk.on_trade(_trade(), [ZONE])
    events = desk.tick(NOW + timedelta(seconds=8))
    assert events[0]["event"] == "zlg"
    closed = desk.on_bar_close(_bar(NOW + timedelta(minutes=15)))
    assert closed[0]["sent"] is False
    assert closed[0]["skip_reason"] == "b_marks"  # fib none → red marks, journalled not dropped
    row = desk.knowledge.get_journal_touch(closed[0]["touch_id"])
    assert row is not None
    assert row["card_id"] == card.card_id
    assert row["ob_status"] == "bull"
    assert row["bos_status"] == "bull"
    assert row["b_gate"] == "b_marks"
    assert row["cav_label"] is not None


def test_get_card_live_bad_json_is_none(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn._cx.execute("BEGIN IMMEDIATE")
    kn._cx.execute(
        "INSERT OR REPLACE INTO claim(id, payload) VALUES (?, ?)",
        ("b_card:BTCUSDT", "{not-json"),
    )
    kn._cx.commit()
    assert kn.get_card_live("BTCUSDT") is None
    kn.close()

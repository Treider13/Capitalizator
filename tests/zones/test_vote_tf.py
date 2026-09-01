"""Map zones vote on working_tf. CAV is the 15m close, not the source horizon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.chronos_data import zones_for
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.patterns.cav import label
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent
from capitalizator.zones.engine import MAP_VOTE_METHODS, ZoneEngine
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
T_BUILD = datetime(2026, 8, 31, 16, 30, tzinfo=UTC)
MAP_METHODS = MAP_VOTE_METHODS


def _day_bar() -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 14, 15, tzinfo=UTC),
        open=Decimal("95"),
        high=Decimal("100"),
        low=Decimal("90"),
        close=Decimal("98"),
        volume=Decimal("10"),
    )


def test_engine_map_zones_use_working_tf() -> None:
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", T_BUILD, [_day_bar()], poc=Decimal("96"))
    mapped = [z for z in zones if z.method in MAP_METHODS]
    assert mapped
    assert {z.method for z in mapped} >= {"prior_day_hl", "prior_session_hl", "vp_hyp"}
    assert {z.tf for z in mapped} == {engine.config.working_tf}


def test_engine_prior_day_15m_close_can_reject() -> None:
    """Same geometry as acceptance fixtures: wick in, close inside support."""
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", T_BUILD, [_day_bar()])
    support = next(z for z in zones if z.method == "prior_day_hl" and z.side == "support")
    assert support.tf == "15m"
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 31, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 31, 16, 30, tzinfo=UTC),
        open=Decimal("90.1"),
        high=Decimal("90.5"),
        low=Decimal("89.9"),
        close=Decimal("90.1"),
    )
    t = datetime(2026, 8, 31, 16, 30, 1, tzinfo=UTC)
    assert label(support, bar, t=t, htf_bias="box") == "REJECT"


def test_foreign_tf_bar_on_map_zone_is_still_noise() -> None:
    """bar.tf == zone.tf stays. A 1h close is not the 15m vote."""
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", T_BUILD, [_day_bar()])
    support = next(z for z in zones if z.method == "prior_day_hl" and z.side == "support")
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 31, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 31, 16, 30, tzinfo=UTC),
        open=Decimal("90.1"),
        high=Decimal("90.5"),
        low=Decimal("89.9"),
        close=Decimal("90.1"),
    )
    t = datetime(2026, 8, 31, 16, 30, 1, tzinfo=UTC)
    assert label(support, hourly, t=t, htf_bias="box") == "NOISE"


def test_two_builds_keep_same_map_ids() -> None:
    engine = ZoneEngine(tick_size=TICK)
    bars = [_day_bar()]
    a = engine.build("BTCUSDT", T_BUILD, bars, poc=Decimal("96"))
    b = engine.build("BTCUSDT", T_BUILD, bars, poc=Decimal("96"))
    assert [z.zone_id for z in a] == [z.zone_id for z in b]


def test_desk_engine_prior_day_15m_close_is_reject(tmp_path: Path) -> None:
    """Organism path: engine zone, not a hand-tagged 15m fixture."""
    engine = ZoneEngine(tick_size=TICK)
    support = next(
        z
        for z in engine.build("BTCUSDT", T_BUILD, [_day_bar()])
        if z.method == "prior_day_hl" and z.side == "support"
    )
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), tick_size=TICK)
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=T_BUILD,
            seq=1,
            bids=(("90.0", "20"),),
            asks=(("90.2", "20"),),
        )
    )
    desk.on_book("BTCUSDT", book)
    print_ts = T_BUILD - timedelta(minutes=15)
    desk.on_event(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=print_ts,
            recv_ts=print_ts,
            payload={"px": "90.1", "qty": "1", "side": "sell"},
        ),
        [support],
    )
    desk.tick(print_ts + timedelta(seconds=8))
    events = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=print_ts,
            close_ts=T_BUILD,
            open=Decimal("90.1"),
            high=Decimal("90.5"),
            low=Decimal("89.9"),
            close=Decimal("90.1"),
        )
    )
    assert events
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["cav_label"] == "REJECT"
    assert row["cav_tf"] == "15m"


def test_persist_drops_stale_1d_map_row(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), tick_size=TICK)
    old = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("90"),
        hi=Decimal("90.2"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 31, tzinfo=UTC),
    )
    desk.knowledge.put_zone(
        old.zone_id,
        {
            "zone_id": old.zone_id,
            "symbol": old.symbol,
            "tf": old.tf,
            "side": old.side,
            "lo": str(old.lo),
            "hi": str(old.hi),
            "method": old.method,
            "created_as_of": old.created_as_of.isoformat(),
        },
    )
    fresh = next(
        z
        for z in ZoneEngine(tick_size=TICK).build("BTCUSDT", T_BUILD, [_day_bar()])
        if z.method == "prior_day_hl" and z.side == "support"
    )
    desk.persist_zones([fresh])
    stored = desk.knowledge.list_zones(symbol="BTCUSDT")
    assert all(str(row.get("tf")) == desk.config.working_tf for row in stored)
    assert old.zone_id not in {str(row.get("zone_id")) for row in stored}
    assert fresh.zone_id in {str(row.get("zone_id")) for row in stored}


def test_chronos_rebuilds_when_stored_map_tf_is_1d(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    old = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("90"),
        hi=Decimal("90.2"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 31, tzinfo=UTC),
    )
    knowledge.put_zone(
        old.zone_id,
        {
            "zone_id": old.zone_id,
            "symbol": old.symbol,
            "tf": old.tf,
            "side": old.side,
            "lo": str(old.lo),
            "hi": str(old.hi),
            "method": old.method,
            "created_as_of": old.created_as_of.isoformat(),
        },
    )
    knowledge.close()
    sink = ParquetSink(vault.tape)
    for ts, px in (
        (datetime(2026, 8, 30, 14, 0, tzinfo=UTC), "90"),
        (datetime(2026, 8, 30, 14, 10, tzinfo=UTC), "100"),
    ):
        sink.write(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                payload={"px": px, "qty": "1", "side": "buy"},
            )
        )
    shown = zones_for(vault, symbol="BTCUSDT", now=T_BUILD)
    assert shown
    assert all(str(row.get("tf")) != "1d" for row in shown if row.get("method") in MAP_METHODS)
    assert any(row.get("method") == "prior_day_hl" for row in shown)

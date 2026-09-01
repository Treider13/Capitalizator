"""§2: desk serve reads parquet tape into the loop. Empty tape is empty."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from capitalizator.desk.__main__ import serve_loop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_serve_loop_consumes_parquet_trade(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    ParquetSink(vault.tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100.4", "qty": "1", "side": "sell"},
        )
    )
    knowledge = open_knowledge(vault)
    n = {"i": 0}

    def should_stop() -> bool:
        n["i"] += 1
        return n["i"] >= 2

    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=should_stop,
        idle_s=0,
    )
    knowledge.close()
    assert desk.state_for("BTCUSDT").trades
    assert desk.state_for("BTCUSDT").trades[0].payload["px"] == "100.4"


def test_serve_loop_ticks_zlg_after_window(tmp_path: Path) -> None:
    from datetime import timedelta
    from decimal import Decimal

    from capitalizator.zones.model import Zone

    vault = init_vault(tmp_path / "desk")
    sink = ParquetSink(vault.tape)
    sink.write(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=1,
            payload={"bids": [["100.4", "20"]], "asks": [["100.6", "20"]]},
        )
    )
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100.4", "qty": "1", "side": "sell"},
        )
    )
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )
    knowledge = open_knowledge(vault)
    n = {"i": 0}

    def should_stop() -> bool:
        n["i"] += 1
        return n["i"] >= 2

    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=should_stop,
        idle_s=0,
        now=NOW + timedelta(seconds=8),
        extra_zones=(zone,),
    )
    knowledge.close()
    st = desk.state_for("BTCUSDT")
    assert st.state in {"LABEL_ZLG", "IDLE", "JURY"}
    assert st.state != "ARM_ZLG"


def test_serve_loop_builds_zones_from_closed_bars(tmp_path: Path) -> None:
    """Wave 4 / §3: VPS serve has no extra_zones — prior_day_hl comes from tape."""
    vault = init_vault(tmp_path / "desk")
    sink = ParquetSink(vault.tape)
    day0 = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=day0,
            recv_ts=day0,
            payload={"px": "99.0", "qty": "1", "side": "sell"},
        )
    )
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=day0 + timedelta(minutes=10),
            recv_ts=day0 + timedelta(minutes=10),
            payload={"px": "105.0", "qty": "1", "side": "buy"},
        )
    )
    sink.write(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=1,
            payload={"bids": [["99.0", "20"]], "asks": [["99.2", "20"]]},
        )
    )
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "99.1", "qty": "1", "side": "sell"},
        )
    )
    knowledge = open_knowledge(vault)
    n = {"i": 0}

    def should_stop() -> bool:
        n["i"] += 1
        return n["i"] >= 2

    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=should_stop,
        idle_s=0,
        now=NOW + timedelta(seconds=8),
    )
    knowledge.close()
    st = desk.state_for("BTCUSDT")
    assert st.last_touch is not None or st.state in {"LABEL_ZLG", "IDLE", "JURY"}
    assert any(z.method == "prior_day_hl" for z in desk.registry._zones.values())


def test_consume_tape_closes_h4_and_d1_from_prints(tmp_path: Path) -> None:
    """§6.3 / wave 4: HTF 4h and D1 close from the same prints. Else htf_bias is always unknown."""
    from capitalizator.desk.loop import DeskLoop
    from capitalizator.desk.tape import consume_tape
    from capitalizator.zones.map import ZoneMap

    vault = init_vault(tmp_path / "desk")
    sink = ParquetSink(vault.tape)
    t0 = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(0, 26 * 60, 15):
        ts = t0 + timedelta(minutes=i)
        px = 100 + (i % 240) / 10
        sink.write(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                payload={"px": str(px), "qty": "1", "side": "buy"},
            )
        )
    now = t0 + timedelta(hours=26)
    desk = DeskLoop(knowledge=open_knowledge(vault))
    consume_tape(desk, vault.tape, seen=set(), now=now)
    st = desk.state_for("BTCUSDT")
    h4 = [b for b in st.bars if b.tf == "4h"]
    d1 = [b for b in st.bars if b.tf == "1d"]
    assert len(h4) >= 3, f"expected closed 4h bars from tape, got {len(h4)}"
    assert len(d1) >= 1, f"expected a closed 1d bar from tape, got {len(d1)}"
    when = h4[-1].close_ts + timedelta(microseconds=1)
    assert ZoneMap().htf_bias("BTCUSDT", when, st.bars) != "unknown"


def test_htf_bar_close_does_not_steal_working_tf_cav(tmp_path: Path) -> None:
    """§6.3/§6.5: CAV is the 15m vote. H4 close first must not stamp NOISE and drop the touch."""
    from decimal import Decimal

    from capitalizator.book.reconstruct import Book
    from capitalizator.card.live import CardLive
    from capitalizator.desk.loop import DeskLoop
    from capitalizator.recorder.rest_snapshot import BookSnapshot
    from capitalizator.zones.model import Bar, Zone

    vault = init_vault(tmp_path / "desk")
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )
    desk = DeskLoop(knowledge=open_knowledge(vault), tick_size=Decimal("0.1"))
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
    desk.on_event(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100.4", "qty": "1", "side": "sell"},
        ),
        [zone],
    )
    desk.tick(NOW + timedelta(seconds=8))
    stolen = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="4h",
            open_ts=NOW - timedelta(hours=3, minutes=45),
            close_ts=NOW + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("10"),
        )
    )
    assert stolen == []
    assert desk.state_for("BTCUSDT").last_touch is not None
    close_15 = NOW + timedelta(minutes=15)
    desk.knowledge.put_card_live(
        "BTCUSDT",
        CardLive(
            symbol="BTCUSDT",
            bearing_verdict="propose",
            known_at=close_15,
            fib_zone="OTE",
            fib_level="0.718",
            rsi_htf="58.40",
            fvg_status="filled",
            sweep_status="done",
            pluses=("session_profile", "htf_ok", "rvol_above_2"),
            minuses=("base_rate_unknown", "spread_cost"),
        ).to_payload(),
    )
    events = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=NOW,
            close_ts=NOW + timedelta(minutes=15),
            open=Decimal("100.5"),
            high=Decimal("101"),
            low=Decimal("99.9"),
            close=Decimal("100.4"),
            volume=Decimal("1"),
        )
    )
    assert events
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["cav_label"] == "REJECT"


def test_empty_tape_does_not_invent(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    n = {"i": 0}
    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=lambda: (n.update(i=n["i"] + 1) or n["i"] >= 1),
        idle_s=0,
    )
    knowledge.close()
    assert desk.symbols == {}

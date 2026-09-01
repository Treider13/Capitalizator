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

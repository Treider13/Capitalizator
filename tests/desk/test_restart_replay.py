"""Restart catch-up: restored open is frozen; decided journal touches do not re-arm."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.exec.paper import PaperPosition
from capitalizator.memory.registry import Touch
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
T0 = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=T0 - timedelta(days=1),
)


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "desk")), tick_size=TICK)


def _trade(ts: datetime, px: str, qty: str = "1") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": qty, "side": "sell"},
    )


def test_trail_state_after_restart_keeps_profit_stop(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    pos = PaperPosition(
        paper_id="p1",
        touch_id="t1",
        symbol="BTCUSDT",
        side="buy",
        limit_px=Decimal("100"),
        qty=Decimal("1"),
        stop=Decimal("101"),
        tp=None,
        tick=TICK,
        created_at=T0,
        valid_until=T0 + timedelta(hours=1),
        max_hold=timedelta(hours=6),
        source="demo",
        tag="bounce",
        risk_usdt=Decimal("2"),
        state="open",
        entry_px=Decimal("100"),
        initial_stop=Decimal("98"),
        half_taken=True,
        trailing_distance=Decimal("2"),
    )
    stt = desk._trail_state(pos)
    assert stt.stop == Decimal("101")
    assert stt.initial_stop == Decimal("98")
    assert stt.half_taken is True and stt.phase == 1
    assert stt.exchange_trailing_armed is True


def test_restored_open_skips_historical_soft_exit(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    cutoff = T0 + timedelta(hours=2)
    desk.paper.open_replay_cutoff = cutoff
    desk.paper.restore(
        [
            {
                "paper_id": "p1",
                "touch_id": "t1",
                "symbol": "BTCUSDT",
                "side": "buy",
                "limit_px": "100",
                "qty": "1",
                "stop": "99",
                "tp": None,
                "tick": "0.1",
                "created_at": T0.isoformat(),
                "valid_until": (T0 + timedelta(hours=1)).isoformat(),
                "max_hold": 21600,
                "source": "demo",
                "tag": "bounce",
                "risk_usdt": "2",
                "state": "open",
                "entry_px": "100",
                "qty_open": "1",
                "filled_at": (T0 + timedelta(seconds=1)).isoformat(),
                "initial_stop": "98",
                "structural": "99.5",
            }
        ]
    )
    pos = desk.paper.positions["p1"]
    assert pos.restored is True
    st = desk.state_for("BTCUSDT")
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=T0 + timedelta(minutes=15),
        close_ts=T0 + timedelta(minutes=30),
        open=Decimal("100"),
        high=Decimal("100.2"),
        low=Decimal("99.0"),
        close=Decimal("99.1"),
    )
    assert desk._trail_on_bar(st, bar) == []
    assert pos.state == "open"


def test_serve_sets_cutoff_once_does_not(tmp_path: Path) -> None:
    from capitalizator.desk.__main__ import run_once, serve_loop

    vault = init_vault(tmp_path / "once")
    kn = open_knowledge(vault)
    once = run_once(vault=vault, knowledge=kn, now=T0)
    assert once.paper.open_replay_cutoff is None
    kn.close()

    vault2 = init_vault(tmp_path / "serve")
    kn2 = open_knowledge(vault2)
    n = {"i": 0}
    served = serve_loop(
        vault=vault2,
        knowledge=kn2,
        should_stop=lambda: (n.update(i=n["i"] + 1) or n["i"] >= 1),
        idle_s=0,
        now=T0,
    )
    kn2.close()
    assert served.paper.open_replay_cutoff == T0


def test_resolved_journal_touch_does_not_rearm(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.registry._zones[ZONE.zone_id] = ZONE
    ts = T0 + timedelta(minutes=10)
    px, qty = Decimal("100.4"), Decimal("1")
    touch = Touch.create(zone_id=ZONE.zone_id, ts=ts, trade_px=px, trade_qty=qty)
    desk.knowledge.put_journal_touch(
        touch.touch_id,
        {"touch_id": touch.touch_id, "zone_id": ZONE.zone_id, "outcome": "bounce"},
    )
    out = desk.on_trade(_trade(ts, "100.4"), [ZONE])
    assert out == []
    assert all(t.touch_id != touch.touch_id for t in desk.registry.touches)
    later = desk.on_trade(_trade(ts + timedelta(minutes=1), "100.4"), [ZONE])
    assert later and later[0]["event"] == "armed"
    assert later[0]["touch_id"] != touch.touch_id

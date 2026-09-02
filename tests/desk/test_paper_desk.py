"""Desk ↔ paper: shadow ideas trade on paper 24/7; demo intents move the account."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
WINDOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)  # inside the desk window
# 1% wide zone on a 100k coin: R ≈ 1000 USDT/coin so the EV gate passes.
ZONE = Zone.create(
    symbol="BTCUSDT", tf="15m", side="support", lo=Decimal("99000"), hi=Decimal("100000.2"),
    method="prior_day_hl", created_as_of=CREATED,
)


def _trade(ts: datetime, px: str, side: str = "sell", qty: str = "1") -> MarketEvent:
    return MarketEvent(
        stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts, recv_ts=ts,
        payload={"px": px, "qty": qty, "side": side},
    )


def _desk(tmp_path: Path, mode: str) -> DeskLoop:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode=mode, tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    for i in range(20):
        desk.registry.touches.append(replace(
            Touch.create(zone_id=ZONE.zone_id, ts=CREATED + timedelta(seconds=i + 1),
                         trade_px=Decimal("100000.1"), trade_qty=Decimal("1")),
            outcome="bounce", cav_label="REJECT", gesture="DEFEND", tape_eaten=False,
            btc_regime="box",
        ))
    desk.btc.regime = "box"
    book = Book(tick_size="0.1")
    book.apply_snapshot(BookSnapshot(symbol="BTCUSDT", exchange_ts=WINDOW, seq=1,
                                     bids=(("100000.1", "20"),), asks=(("100000.3", "20"),)))
    desk.on_book("BTCUSDT", book)
    return desk


def _arm_and_close(desk: DeskLoop) -> dict:
    desk.on_trade(_trade(WINDOW, "100000.1"), [ZONE])
    live = desk.state_for("BTCUSDT").last_touch
    desk.on_event(MarketEvent(stream="book_diff", exchange="bybit", symbol="BTCUSDT",
                              exchange_ts=WINDOW + timedelta(seconds=2),
                              recv_ts=WINDOW + timedelta(seconds=2), seq=2,
                              payload={"b": [["100000.1", "45"]], "a": []}))
    desk.registry._patch(touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED")
    desk.tick(WINDOW + timedelta(seconds=8))
    bar = Bar(symbol="BTCUSDT", tf="15m", open_ts=WINDOW - timedelta(minutes=10),
              close_ts=WINDOW + timedelta(minutes=5), open=Decimal("100000.1"),
              high=Decimal("100000.4"), low=Decimal("98999"), close=Decimal("100000.2"))
    return desk.on_bar_close(bar)[0]


def test_shadow_and_fade_trade_on_paper_in_off_mode(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "off")
    ev = _arm_and_close(desk)
    assert ev["jury"] == "ACCORD" and ev["sent"] is False
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert set(row["paper_ids"]) == {"shadow", "fade"}
    shadow = desk.paper.positions[row["paper_ids"]["shadow"]]
    fade = desk.paper.positions[row["paper_ids"]["fade"]]
    assert shadow.side == "buy" and fade.side == "sell"
    assert shadow.stop < shadow.limit_px < shadow.tp
    assert fade.stop > fade.limit_px > fade.tp
    assert shadow.stop == Decimal("98999") - Decimal("0.8")  # behind the spring wick
    # tape: seller hits our bid → filled; then +1R → half; then tp on the rest
    t = WINDOW + timedelta(minutes=6)
    desk.on_trade(_trade(t, "100000.1", side="sell"), [ZONE])
    assert shadow.state == "open"
    r = shadow.r_px
    desk.on_trade(_trade(t + timedelta(minutes=1), str(Decimal("100000.1") + r + 1)), [ZONE])
    assert shadow.half_taken
    desk.on_trade(_trade(t + timedelta(minutes=2), str(shadow.tp + 1)), [ZONE])
    assert shadow.state == "closed" and shadow.exit_reason == "tp"
    # the fade (sell at the level) was filled by the same tape and stopped out on the way up
    assert fade.state == "closed" and fade.exit_reason == "stop"
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert Decimal(row["paper"]["shadow"]["r_net"]) > 1
    assert Decimal(row["paper"]["fade"]["r_net"]) < 0
    trades = desk.knowledge.paper_trades()
    assert {t["source"] for t in trades} == {"shadow", "fade"}
    day = json.loads(desk.knowledge.meta("paper_day:2026-08-31"))
    assert day["n_paper"] == 1 and Decimal(day["r_paper_net"]) > 1
    assert day["n_fade"] == 1 and Decimal(day["r_fade_net"]) < 0
    # the account did not move: shadows are not demo
    assert desk.account.equity == desk.risk_config.paper_equity
    assert desk.account.open == {}


def test_demo_intent_is_paper_traded_and_moves_the_account(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "demo")
    ev = _arm_and_close(desk)
    assert ev["sent"] is True, desk.knowledge.get_journal_touch(ev["touch_id"]).get("send_skip")
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    demo = desk.paper.positions[row["paper_ids"]["demo"]]
    assert demo.qty == Decimal(desk.knowledge.pending_intents()[0]["payload"]["qty"])
    assert "BTCUSDT" in desk.account.open
    equity0 = desk.account.equity
    t = WINDOW + timedelta(minutes=6)
    desk.on_trade(_trade(t, "100000.1", side="sell"), [ZONE])
    assert demo.state == "open"
    desk.on_trade(_trade(t + timedelta(minutes=1), str(demo.stop - 1)), [ZONE])
    assert demo.state == "closed" and demo.exit_reason == "stop"
    # loss = sized risk (deposit_share binds: 10% margin × 3x → 0.3 BTC) + slippage + fees,
    # never more than the 1% target risk. The account, halts and one-position rule moved.
    assert desk.account.equity < equity0
    lost = equity0 - desk.account.equity
    sizing = row["sizing"]
    assert sizing["binding"] == "deposit_share"
    risk = Decimal(sizing["risk_usdt"])
    assert risk < lost < risk + demo.fees + demo.qty * TICK * 2
    assert lost < Decimal("0.01") * equity0
    assert desk.account.open == {}
    assert desk.risk.allow_entry("BTCUSDT") is True
    snap = json.loads(desk.knowledge.meta("account"))
    assert Decimal(snap["equity"]) == desk.account.equity
    assert Decimal(snap["day_pnl_pct"]) < 0


def test_flatten_command_closes_paper_positions(tmp_path: Path) -> None:
    desk = _desk(tmp_path, "off")
    ev = _arm_and_close(desk)
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    t = WINDOW + timedelta(minutes=6)
    desk.on_trade(_trade(t, "100000.1", side="sell"), [ZONE])
    out = desk.on_event({"kind": "flatten", "symbol": "BTCUSDT", "now": t + timedelta(minutes=1)})
    assert out[0]["paper_flattened"] == 2
    assert desk.paper.positions == {}
    shadow = next(p for p in desk.paper.closed if p.paper_id == row["paper_ids"]["shadow"])
    assert shadow.exit_reason == "flatten" and shadow.exit_px == Decimal("100000.1")

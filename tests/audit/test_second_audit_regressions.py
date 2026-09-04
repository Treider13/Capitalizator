"""Regressions for the second deep audit (2026-09-03): each test is one finding that
the previous suite did not see because its fixtures mocked the wrong shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.paper import PaperEngine
from capitalizator.gateway.tracker import PositionTracker
from capitalizator.gateway.ws import PrivateFeed
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.account import Account
from capitalizator.risk.config import RiskConfig
from capitalizator.types import MarketEvent
from capitalizator.zlg.gesture import BookAdd, BookPull, survived_adds

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _print(px: str, qty: str, taker: str, when: datetime) -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=when,
                       recv_ts=when, payload={"px": px, "qty": qty, "side": taker})


# --- A1: Bybit v5 WS `position` carries entryPrice, REST carries avgPrice ------------
def test_ws_position_entry_price_matches_rest_avg_price_without_a_mismatch() -> None:
    tr = PositionTracker()
    feed = PrivateFeed(tr)
    feed.enqueue({"topic": "position", "data": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3",
                                                 "entryPrice": "65000.5", "stopLoss": "64300",
                                                 "updatedTime": str(int(NOW.timestamp() * 1000))}]})
    assert feed.drain(now=NOW) == 1
    assert tr.positions["BTCUSDT"].avg_price == Decimal("65000.5")
    # REST rounds the average by a fraction of a bp: not a mismatch
    mm = tr.reconcile([{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "avgPrice": "65000.51",
                        "stopLoss": "64300"}], now=NOW)
    assert mm == []
    # a real difference still is
    mm = tr.reconcile([{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "avgPrice": "66000",
                        "stopLoss": "64300"}], now=NOW)
    assert [m["field"] for m in mm] == ["avg_price"]


def test_ws_liveness_is_recent_frames_not_ever_connected() -> None:
    tr = PositionTracker()
    feed = PrivateFeed(tr)
    feed.enqueue({"topic": "position", "data": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3",
                                                 "entryPrice": "65000", "stopLoss": "64300"}]})
    feed.drain(now=NOW)
    # WS silent for 10 minutes, REST says flat → the position is gone, not a `size` mismatch loop
    later = NOW + timedelta(minutes=10)
    mm = tr.reconcile([], now=later)
    assert tr.open_symbols() == []
    assert all(m.get("field") != "size" for m in mm)


def test_acknowledgement_ends_with_the_position() -> None:
    tr = PositionTracker()
    tr.reconcile([{"symbol": "ETHUSDT", "side": "Buy", "size": "1", "avgPrice": "4000"}], now=NOW,
                 expected=set())
    assert tr.unknown_symbols() == ["ETHUSDT"]
    assert tr.acknowledge("ETHUSDT")
    tr.reconcile([{"symbol": "ETHUSDT", "side": "", "size": "0"}], now=NOW + timedelta(minutes=1),
                 expected=set())
    assert "ETHUSDT" not in tr.acknowledged
    # the next stranger on the same symbol is unknown again
    tr.reconcile([{"symbol": "ETHUSDT", "side": "Sell", "size": "2", "avgPrice": "4100"}],
                 now=NOW + timedelta(minutes=2), expected=set())
    assert tr.unknown_symbols() == ["ETHUSDT"]


# --- A2: replayed tape never fills or stops a twin that is younger than the print -----
def test_paper_ignores_prints_older_than_the_twin() -> None:
    eng = PaperEngine()
    eng.submit(paper_id="p1", touch_id="t1", symbol="BTCUSDT", side="buy", limit_px=Decimal("100"),
               qty=Decimal("1"), stop=Decimal("99"), tp=Decimal("102"), tick=Decimal("0.1"), now=NOW,
               valid_for=timedelta(hours=1), source="demo", tag="bounce")
    pos = eng.positions["p1"]
    # a print from an hour before we rested, through the stop: history, not our trade
    eng.on_print(_print("98", "5", "sell", NOW - timedelta(hours=1)))
    assert pos.state == "pending"
    eng.on_print(_print("99.9", "5", "sell", NOW + timedelta(seconds=1)))
    assert pos.state == "open"
    # and once open, prints older than the fill are ignored too
    eng.on_print(_print("98", "5", "sell", NOW - timedelta(minutes=30)))
    assert pos.state == "open"


# --- A3: the day never rolls backwards ---------------------------------------------
def test_account_day_roll_is_monotonic_and_survives_a_restart(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    acct = Account(config=RiskConfig(), knowledge=kn)
    acct.roll(NOW)
    start = acct.equity
    acct.set_equity(start * Decimal("0.96"), source=acct.equity_source, now=NOW)  # −4% → day halt
    assert acct.halts.halted and acct.halts.reason == "day"
    # a replayed print from yesterday must not lift the halt or re-baseline the day
    acct.roll(NOW - timedelta(days=1))
    assert acct.halts.halted and acct.halts.day_start == start
    # restart: the day key is persisted, so yesterday's tape still does nothing.
    # `now=NOW` — without it load() rolls to the wall clock, and after 21:00 UTC the
    # Moscow date is already "tomorrow", which lifts the halt (the test then depended
    # on the hour it was run at).
    again = Account.load(kn, RiskConfig(), now=NOW)
    again.roll(NOW - timedelta(days=1))
    assert again.halts.halted and again.halts.day_start == start
    # tomorrow lifts it
    again.roll(NOW + timedelta(days=1))
    assert not again.halts.halted
    kn.close()


# --- B7: a print explains a pull only up to its volume -------------------------------
def test_pull_is_only_laundered_by_printed_volume() -> None:
    t0 = NOW
    add = BookAdd(ts=t0 + timedelta(seconds=1), side="bid", px=Decimal("100"), qty=Decimal("500"))
    pull = BookPull(ts=t0 + timedelta(seconds=3), side="bid", px=Decimal("100"), qty=Decimal("500"))
    micro = [(t0 + timedelta(seconds=2, milliseconds=900), Decimal("100"), Decimal("1"))]
    survived = survived_adds([add], [pull], micro, t0=t0, t1=t0 + timedelta(seconds=8))
    # 499 of 500 pulled unexplained → at most the printed lot survived
    assert sum(q for _, q in survived) <= Decimal("1")
    real = [(t0 + timedelta(seconds=2, milliseconds=900), Decimal("100"), Decimal("500"))]
    survived = survived_adds([add], [pull], real, t0=t0, t1=t0 + timedelta(seconds=8))
    assert survived and survived[0][1] == Decimal("500")  # the whole level executed: it survived

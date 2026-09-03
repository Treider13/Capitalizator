"""The BounceSnapshot the desk hands the strategy carries measured facts, not defaults.

`typical_move` used to stay at the dataclass default 1% for every symbol — the spread
screener compared costs with a constant. Now it is ATR14 / price of the working TF when
15 bars exist, else the range of the bar that just closed; `lev` is the operator's
max_lev; `volume_ok` is the closed bar's liquidity label.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.exec.strategy_bounce import BounceSnapshot
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


def _trade(ts: datetime, px: str, side: str = "sell", qty: str = "1") -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                       recv_ts=ts, payload={"px": px, "qty": qty, "side": side})


class _Capture:
    def __init__(self) -> None:
        self.snaps: list[BounceSnapshot] = []
        self.budget = None

    def propose(self, snap: BounceSnapshot):  # noqa: ANN201
        self.snaps.append(snap)
        return None


def _desk(tmp_path: Path) -> tuple[DeskLoop, _Capture]:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="demo", tick_size=TICK)
    desk.registry._zones[SUP.zone_id] = SUP
    for i in range(20):
        desk.registry.touches.append(replace(
            Touch.create(zone_id=SUP.zone_id, ts=CREATED + timedelta(seconds=i + 1),
                         trade_px=Decimal("100000"), trade_qty=Decimal("1")),
            outcome="bounce", cav_label="REJECT", gesture="DEFEND", tape_eaten=False,
            btc_regime="box"))
    desk.btc.regime = "box"
    book = Book(tick_size=str(TICK))
    book.apply_snapshot(BookSnapshot(symbol="BTCUSDT", exchange_ts=WINDOW, seq=1,
                                     bids=(("100000", "20"),), asks=(("100000.2", "20"),)))
    desk.on_book("BTCUSDT", book)
    cap = _Capture()
    desk.strategy = cap  # type: ignore[assignment]
    return desk, cap


def _arm(desk: DeskLoop, when: datetime = WINDOW) -> None:
    desk.on_trade(_trade(when, "100000"), [SUP])
    live = desk.state_for("BTCUSDT").last_touch
    book = desk.state_for("BTCUSDT").book
    bigger = book.level("bid", "100000") + 45
    desk.on_event(MarketEvent(stream="book_diff", exchange="bybit", symbol="BTCUSDT",
                              exchange_ts=when + timedelta(seconds=2),
                              recv_ts=when + timedelta(seconds=2), seq=book.seq + 1,
                              payload={"b": [["100000", str(bigger)]], "a": []}))
    desk.registry._patch(touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED")
    desk.tick(when + timedelta(seconds=8))


def _bar(close_ts: datetime, *, high: str, low: str, volume: str | None = "10") -> Bar:
    return Bar(symbol="BTCUSDT", tf="15m", open_ts=close_ts - timedelta(minutes=15),
               close_ts=close_ts, open=Decimal("100000"), high=Decimal(high), low=Decimal(low),
               close=Decimal("100000.2"),
               volume=None if volume is None else Decimal(volume))


def test_without_atr_typical_move_is_unmeasured_not_one_percent(tmp_path: Path) -> None:
    desk, cap = _desk(tmp_path)
    _arm(desk)
    bar = _bar(WINDOW + timedelta(minutes=5), high="100300", low="98990")
    ev = desk.on_bar_close(bar)[0]
    assert len(cap.snaps) == 1
    snap = cap.snaps[0]
    assert snap.typical_move is None  # no ATR14 yet → the screen is not measured
    assert snap.lev == desk.risk_config.max_lev
    assert snap.volume_ok is True
    row = desk.knowledge.get_journal_touch(ev["touch_id"])
    assert row["typical_move_source"] == "no_atr_yet"
    assert row["typical_move"] is None
    # the strategy stub refused: the desk journals that as a reason, not as silence
    assert row["send_skip"].startswith("propose:")


def test_fifteen_bars_give_atr14_over_price(tmp_path: Path) -> None:
    desk, cap = _desk(tmp_path)
    st = desk.state_for("BTCUSDT")
    for i in range(15, 0, -1):
        st.bars.append(_bar(WINDOW - timedelta(minutes=15 * i), high="100150", low="99850"))
    _arm(desk)
    bar = _bar(WINDOW + timedelta(minutes=5), high="100300", low="98990")
    desk.on_bar_close(bar)
    snap = cap.snaps[0]
    atr = desk._atr_for(st)
    assert atr is not None
    assert snap.typical_move == atr / snap.price
    # the closing bar's own range is wider than the 14-bar mean: the mean was used
    assert snap.typical_move < (bar.high - bar.low) / snap.price


def test_illiquid_closed_bar_turns_volume_ok_off(tmp_path: Path) -> None:
    desk, cap = _desk(tmp_path)
    st = desk.state_for("BTCUSDT")
    st.bars.append(_bar(WINDOW - timedelta(minutes=15), high="100150", low="99850", volume="0"))
    _arm(desk)
    desk.on_bar_close(_bar(WINDOW + timedelta(minutes=5), high="100300", low="98990", volume="0"))
    assert cap.snaps[0].volume_ok is False

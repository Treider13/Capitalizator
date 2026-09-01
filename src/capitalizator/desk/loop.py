"""Per-symbol 24/7 state machine. No global 'all symbols then jury' pass.

IDLE → ARM_ZLG → LABEL_ZLG → JURY. Send only inside the desk window
when user_mode is demo|live and jury is ACCORD. Shadow always writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from capitalizator.book.reconstruct import Book
from capitalizator.btc.veto import BtcVeto
from capitalizator.card.first_fact import resolve as resolve_first_fact
from capitalizator.desk.pictures import needs_new_card, picture_for
from capitalizator.desk.session_name import session_name
from capitalizator.exec.failed_break import FailedBreak
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.exec.shadow import ShadowWriter
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.jury.desk import decide, voices_for_bounce, voices_for_breakout, voices_for_failed_break
from capitalizator.memory.registry import Registry, Touch
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.product import DEFAULT_MODE
from capitalizator.patterns.cav import label as cav_label
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.risk.session import SessionWindow, in_desk_window
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zlg.gesture import ZLG, BookAdd
from capitalizator.zones.config import load_registry
from capitalizator.zones.map import ZoneMap
from capitalizator.zones.model import Bar, Zone

State = Literal["IDLE", "ARM_ZLG", "LABEL_ZLG", "JURY"]


@dataclass
class SymbolState:
    symbol: str
    book: Book
    book_pre: Book | None = None
    state: State = "IDLE"
    armed_at: datetime | None = None
    adds: list[BookAdd] = field(default_factory=list)
    trades: list[MarketEvent] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    last_touch: Touch | None = None


@dataclass
class BtcBus:
    """Read-only BTC bus for alts. Writer is the BTC symbol loop."""

    regime: str | None = None
    broke_support: bool = False
    broke_resistance: bool = False
    bars: list[Bar] = field(default_factory=list)


class DeskLoop:
    def __init__(
        self,
        *,
        knowledge: Knowledge,
        user_mode: str = DEFAULT_MODE,
        tick_size: Decimal = Decimal("0.1"),
        calendar: tuple[NewsRow, ...] = (),
        btc: BtcBus | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.user_mode = user_mode
        self.tick_size = tick_size
        self.calendar = calendar
        self.btc = btc if btc is not None else BtcBus()
        self.config = load_registry()
        self.symbols: dict[str, SymbolState] = {}
        self.registry = Registry(tick_size=tick_size, config=self.config)
        self.shadow = ShadowWriter()
        self.session = SessionWindow()
        self.risk = RiskEngine()
        self.halts = Halts(start_equity=Decimal("100000"))
        self.strategy = BounceStrategy(
            risk=self.risk,
            halts=self.halts,
            session=self.session,
            registry=self.config,
            desk_mode=user_mode if user_mode in {"demo", "live"} else "off",
            require_card=False,
            require_jury=True,
            check_tape=True,
            check_wall=True,
        )
        self.zlg = ZLG(tick_size=tick_size, config=self.config)
        self.tape = TapeClassifier()
        self.zones_map = ZoneMap(self.config)
        self.first_minute = FirstMinute()
        self.btc_veto = BtcVeto()

    def state_for(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(symbol=symbol, book=Book(tick_size=str(self.tick_size)))
        return self.symbols[symbol]

    def on_book(self, symbol: str, book: Book) -> None:
        self.state_for(symbol).book = book

    def on_add(self, symbol: str, add: BookAdd) -> None:
        self.state_for(symbol).adds.append(add)

    def on_bar_close(self, bar: Bar) -> list[dict[str, Any]]:
        st = self.state_for(bar.symbol)
        st.bars.append(bar)
        if bar.symbol == "BTCUSDT":
            self.btc.bars.append(bar)
        if st.last_touch is None:
            return []
        return self._eval_cav_and_jury(st, bar)

    def on_trade(self, trade: MarketEvent, zones: list[Zone]) -> list[dict[str, Any]]:
        require_utc(trade.exchange_ts)
        st = self.state_for(trade.symbol)
        st.trades.append(trade)
        opened = self.registry.on_trade(trade, zones)
        if not opened:
            return []
        touch = opened[-1]
        st.last_touch = touch
        if st.book.ready:
            st.book_pre = st.book.snapshot_copy()
        st.state = "ARM_ZLG"
        st.armed_at = trade.exchange_ts
        return [{"event": "armed", "touch_id": touch.touch_id, "symbol": trade.symbol}]

    def tick(self, now: datetime) -> list[dict[str, Any]]:
        when = require_utc(now)
        out: list[dict[str, Any]] = []
        window = timedelta(seconds=self.config.zlg_window_s)
        for st in self.symbols.values():
            if st.state != "ARM_ZLG" or st.armed_at is None or st.last_touch is None:
                continue
            if when < st.armed_at + window:
                continue
            out.extend(self._label_zlg(st, when))
        return out

    def _label_zlg(self, st: SymbolState, now: datetime) -> list[dict[str, Any]]:
        touch = st.last_touch
        if touch is None:
            return []
        zone = self.registry.zone(touch.zone_id)
        book = st.book_pre or st.book
        bid, ask = book.best() if book.ready else (None, None)
        mid = ((bid + ask) / 2) if bid is not None and ask is not None else touch.trade_px
        hit_side = "bid" if zone.side == "support" else "ask"
        opp_best = ask if hit_side == "bid" else bid
        if opp_best is None:
            opp_best = touch.trade_px
        result = self.zlg.classify(
            touch,
            st.adds,
            touch.trade_qty,
            hit_side=hit_side,
            mid=mid,
            opp_best=opp_best,
        )
        self.registry.fill_gesture(gesture=result.gesture, touch_id=touch.touch_id)
        if book.ready:
            self.registry.fill_tape(book=book, trades=st.trades, touch_id=touch.touch_id)
        st.state = "LABEL_ZLG"
        return [{"event": "zlg", "touch_id": touch.touch_id, "gesture": result.gesture}]

    def _eval_cav_and_jury(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        touch = st.last_touch
        if touch is None:
            return []
        zone = self.registry.zone(touch.zone_id)
        if bar.close_ts < touch.ts:
            return []
        h4 = self.zones_map.htf_bias(st.symbol, bar.close_ts, st.bars)
        d1 = self.zones_map.htf_d1_bias(st.symbol, bar.close_ts, st.bars)
        cav = cav_label(zone, bar, t=bar.close_ts, htf_bias=h4, closed_bars=st.bars)
        self.registry.fill_cav(cav_label=cav, touch_id=touch.touch_id)
        live = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
        idea = "bounce"
        tag = FailedBreak.tag(zone=zone, bar=bar)
        if tag:
            idea = "failed_break"
        elif cav == "THROUGH":
            idea = "breakout"
        if live.btc_regime is None and st.symbol != "BTCUSDT":
            if self.btc.regime:
                self.registry.fill_btc(regime=self.btc.regime, touch_id=touch.touch_id)
        elif live.btc_regime is None and h4 in {"box", "long", "short"}:
            self.registry.fill_btc(
                regime="box" if h4 == "box" else "trend",
                touch_id=touch.touch_id,
            )
        n_cav = sum(1 for row in self.registry.touches if row.cav_label == cav)
        n_zlg = sum(1 for row in self.registry.touches if row.gesture == live.gesture)
        stamped = self.registry.stamp_jury(
            idea=idea,
            n_cav=n_cav,
            n_zlg=n_zlg,
            touch_id=touch.touch_id,
        )
        row = stamped[0] if stamped else live
        first = resolve_first_fact(row.gesture, n_zlg)
        voice_fn = {
            "bounce": voices_for_bounce,
            "breakout": voices_for_breakout,
            "failed_break": voices_for_failed_break,
        }[idea]
        voices = voice_fn(
            cav=row.cav_label,
            n_cav=n_cav,
            zlg=row.gesture,
            n_zlg=n_zlg,
            tape_eaten=row.tape_eaten,
            btc_regime=row.btc_regime,
            btc_break_against=self.btc.broke_support if idea != "breakout" else self.btc.broke_resistance,
        )
        jury = decide(voices)
        picture = picture_for(idea)
        card_id = str(uuid4()) if needs_new_card(idea) else None
        shadow_would = jury == "ACCORD"
        journal = {
            "touch_id": row.touch_id,
            "zone_id": row.zone_id,
            "touch_ts": row.ts.isoformat(),
            "session_name": session_name(row.ts),
            "session_hour_utc": row.ts.hour,
            "htf_h4": h4,
            "htf_d1": d1,
            "cav_label": row.cav_label,
            "zlg_label": row.gesture,
            "tape_eaten": row.tape_eaten,
            "jury": jury,
            "idea": idea,
            "picture": picture,
            "card_id": card_id,
            "shadow_would": shadow_would,
            "first_fact": first.first_fact,
            "n_cav": n_cav,
            "n_zlg": n_zlg,
            "fib_in_05_1": None,
            "rsi_value": None,
            "fvg_present": None,
            "sweep_wick": None,
            "gex_bg": None,
        }
        self.knowledge.put_journal_touch(row.touch_id, journal)
        payload = {"touch_id": row.touch_id, "jury": jury, "shadow_would": shadow_would}
        self.shadow.write(payload)
        sent = False
        if (
            shadow_would
            and self.user_mode in {"demo", "live"}
            and in_desk_window(row.ts)
            and self.session.allows(row.ts, self.calendar)[0]
        ):
            snap = BounceSnapshot(
                now=row.ts,
                symbol=st.symbol,
                price=row.trade_px,
                tick=self.tick_size,
                trading_mode=self.user_mode,
                zone=zone,
                zones=(zone,),
                calendar=self.calendar,
                idea=idea,
                jury=jury,
                cav_label=row.cav_label,
                zlg_label=row.gesture,
                n_cav=n_cav,
                n_zlg=n_zlg,
                tape_eaten=row.tape_eaten,
                btc_regime=row.btc_regime,
                btc_broke=self.btc.broke_support if st.symbol != "BTCUSDT" else False,
                gesture_n=n_zlg,
                first_minute=self.first_minute.blocks(row.ts, bar.close_ts) if idea == "breakout" else False,
                close_beyond=cav == "THROUGH",
            )
            intent = self.strategy.propose(snap)
            if intent is not None:
                self.knowledge.enqueue_intent(
                    intent.model_dump(mode="json"),
                    created_ts=row.ts.isoformat(),
                )
                sent = True
        st.state = "IDLE"
        st.last_touch = None
        return [{"event": "jury", "touch_id": row.touch_id, "jury": jury, "sent": sent}]

"""Per-symbol 24/7 state machine. No global 'all symbols then jury' pass.

IDLE → ARM_ZLG → LABEL_ZLG → JURY. Send only inside the desk window
when user_mode is demo|live and jury is ACCORD. Shadow always writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from capitalizator.book.reconstruct import Book, BookDirty
from capitalizator.book.wall_watch import WallWatch, last_wall_kind, pulled_without_print
from capitalizator.btc.break_def import Break
from capitalizator.btc.regime import BtcRegime
from capitalizator.btc.veto import BtcVeto
from capitalizator.card.build import from_news as card_from_news
from capitalizator.card.draft import pending_card
from capitalizator.card.first_fact import resolve as resolve_first_fact
from capitalizator.card.live import CardLive, card_is_fresh, touch_line
from capitalizator.card.volume import snapshot as volume_snapshot
from capitalizator.champion.shadow_day import (
    challenger_on,
    challenger_tag,
    persist_day,
    row_day_utc,
)
from capitalizator.desk.pictures import needs_new_card, picture_for
from capitalizator.desk.session_name import session_name
from capitalizator.exec.failed_break import FailedBreak, sweep_wick
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.exec.fvg_mark import fvg_present
from capitalizator.exec.manage import TradeManager
from capitalizator.exec.shadow import ShadowWriter
from capitalizator.exec.spot import SpotAdapter
from capitalizator.exec.strategy_bounce import (
    BounceSnapshot,
    BounceStrategy,
    in_mid_range,
    opposing_target,
    price_in_zone,
)
from capitalizator.exec.tvh import NO_TVH, tvh_ok
from capitalizator.jury.desk import (
    decide,
    voices_for_bounce,
    voices_for_breakout,
    voices_for_failed_break,
)
from capitalizator.memory.journal import JOURNAL_KEYS, empty_journal
from capitalizator.memory.registry import Registry, Touch
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.rules import MacroRules
from capitalizator.news_macro.unlocks import Unlocks
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.phase import breakout_enabled
from capitalizator.ops.product import DEFAULT_MODE, META_HELLO
from capitalizator.patterns.bar_quality import classify_bar_quality
from capitalizator.patterns.cav import label as cav_label
from capitalizator.patterns.width import WidthSample, width_now_from_history, width_rank
from capitalizator.prs.score import PRS
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.risk.session import (
    SessionWindow,
    cpi_day,
    in_desk_window,
    us_data_known_at,
)
from capitalizator.tape.classify import TapeClassifier
from capitalizator.tape.ofi import OFI
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zlg.gesture import ZLG, BookAdd
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import MAP_VOTE_METHODS
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
    book_history: list[tuple[datetime, Book]] = field(default_factory=list)


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
        unlocks: Unlocks | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.user_mode = user_mode
        self.tick_size = tick_size
        self.calendar = calendar
        self.btc = btc if btc is not None else BtcBus()
        self.unlocks = unlocks if unlocks is not None else Unlocks.load()
        self.config = load_registry()
        self.symbols: dict[str, SymbolState] = {}
        self.registry = Registry(tick_size=tick_size, config=self.config)
        self.shadow = ShadowWriter()
        self.session = SessionWindow()
        self.risk = RiskEngine()
        self.halts = Halts(start_equity=Decimal("100000"))
        self.macro = MacroRules(enabled=True)
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
            macro=self.macro,
        )
        self.zlg = ZLG(tick_size=tick_size, config=self.config)
        self.tape = TapeClassifier()
        self.zones_map = ZoneMap(self.config)
        self.first_minute = FirstMinute()
        self.btc_veto = BtcVeto()
        self.btc_regime = BtcRegime(self.zones_map)
        self.manager = TradeManager()
        self.spot = SpotAdapter(knowledge)
        self.shadow_writes: list[dict[str, Any]] = []
        self.last_price: dict[str, Decimal] = {}
        if knowledge.available():
            for symbol, raw in knowledge.last_prices().items():
                try:
                    px = Decimal(str(raw))
                except ArithmeticError:
                    continue
                if px > 0:
                    self.last_price[symbol] = px
        self.open_card_id: dict[str, str] = {}
        self.walls: dict[str, WallWatch] = {}
        self.prs: dict[str, PRS] = {}
        self._width_history: list[WidthSample] = []

    def state_for(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(
                symbol=symbol, book=Book(tick_size=str(self.tick_size))
            )
        return self.symbols[symbol]

    def hello_ok(self) -> bool:
        return self.knowledge.meta(META_HELLO) == "1"

    def contour_on(self) -> bool:
        raw = self.knowledge.meta("contour")
        return raw == "on"

    def persist_zones(self, zones: Sequence[Zone]) -> None:
        if not self.knowledge.available() or not zones:
            return
        vote = self.config.working_tf
        symbols = {z.symbol for z in zones}
        drop_ids: list[str] = []
        for row in self.knowledge.list_zones():
            if str(row.get("symbol") or "") not in symbols:
                continue
            method = str(row.get("method") or "")
            if method not in MAP_VOTE_METHODS:
                continue
            if str(row.get("tf") or "") == vote:
                continue
            zid = row.get("zone_id")
            if zid:
                drop_ids.append(str(zid))
        puts = [
            (
                zone.zone_id,
                {
                    "zone_id": zone.zone_id,
                    "symbol": zone.symbol,
                    "tf": zone.tf,
                    "side": zone.side,
                    "lo": str(zone.lo),
                    "hi": str(zone.hi),
                    "method": zone.method,
                    "created_as_of": zone.created_as_of.isoformat(),
                },
            )
            for zone in zones
        ]
        self.knowledge.apply_zone_writes(drop_ids=drop_ids, puts=puts)

    def _remember_book(self, st: SymbolState, when: datetime) -> None:
        if not st.book.ready:
            return
        st.book_history.append((when, st.book.snapshot_copy()))
        window = timedelta(seconds=self.config.zlg_window_s)
        keep_from = when - window
        # While the 8s ZLG clock is open, do not drop the touch-time book.
        # A later diff would otherwise slide the window and erase OFI/PRS.
        if st.last_touch is not None and st.state == "ARM_ZLG":
            keep_from = st.last_touch.ts
        st.book_history = [row for row in st.book_history if row[0] >= keep_from]
        if self.knowledge.available():
            bids = sorted(
                ((str(px), str(sz)) for px, sz in st.book.levels("bid").items()),
                reverse=True,
            )[:20]
            asks = sorted((str(px), str(sz)) for px, sz in st.book.levels("ask").items())[:20]
            self.knowledge.put_book_levels(
                st.symbol,
                {"symbol": st.symbol, "bids": bids, "asks": asks, "ts": when.isoformat()},
            )

    def _wall_for(self, symbol: str) -> WallWatch:
        if symbol not in self.walls:
            self.walls[symbol] = WallWatch(symbol, min_size=Decimal("50"))
        return self.walls[symbol]

    def _prs_for(self, symbol: str) -> PRS:
        if symbol not in self.prs:
            self.prs[symbol] = PRS(tick_size=self.tick_size, config=self.config)
        return self.prs[symbol]

    def on_book(self, symbol: str, book: Book) -> None:
        self.state_for(symbol).book = book

    def _apply_book_event(self, st: SymbolState, event: MarketEvent) -> None:
        """Apply snapshot/diff from tape. Gap → dirty book, do not invent levels."""
        bids = _levels(event.payload.get("bids") or event.payload.get("b") or [])
        asks = _levels(event.payload.get("asks") or event.payload.get("a") or [])
        seq = event.seq if event.seq is not None else event.payload.get("u")
        if event.stream == "snapshot":
            if seq is None:
                return
            st.book.apply_snapshot(
                BookSnapshot(
                    symbol=event.symbol,
                    exchange_ts=event.exchange_ts,
                    seq=int(seq),
                    bids=bids,
                    asks=asks,
                )
            )
            self._remember_book(st, event.exchange_ts)
            self._wall_for(st.symbol).on_book_and_trade(st.book, ts=event.exchange_ts)
            return
        if event.stream == "book_diff":
            if seq is None:
                st.book = Book(tick_size=str(self.tick_size))
                return
            before = _level_sizes(st.book) if st.book.ready else {}
            try:
                st.book.apply_diff(bids, asks, seq=int(seq))
            except (BookDirty, SeqFault):
                st.book = Book(tick_size=str(self.tick_size))
                return
            _record_adds(st, event.exchange_ts, before)
            self._remember_book(st, event.exchange_ts)
            self._wall_for(st.symbol).on_book_and_trade(st.book, ts=event.exchange_ts)
            return

    def on_add(self, symbol: str, add: BookAdd) -> None:
        self.state_for(symbol).adds.append(add)

    def on_event(
        self,
        event: MarketEvent | dict[str, Any],
        zones: list[Zone] | None = None,
    ) -> list[dict[str, Any]]:
        """One symbol at a time. No global 'all symbols then jury' pass."""
        if isinstance(event, dict):
            kind = str(event.get("kind") or event.get("stream") or "")
            if kind == "mode_change":
                self.user_mode = str(event.get("user_mode") or self.user_mode)
                if self.user_mode in {"demo", "live"}:
                    self.strategy.desk_mode = self.user_mode
                else:
                    self.strategy.desk_mode = "off"
                return [{"event": "mode_change", "user_mode": self.user_mode}]
            if kind == "flatten":
                symbol = str(event.get("symbol") or "")
                if symbol:
                    st = self.state_for(symbol)
                    st.state = "IDLE"
                    st.last_touch = None
                    st.adds.clear()
                    st.trades.clear()
                    st.book_pre = None
                action = self.manager.on_refute(load_bearing=True, verdict="REFUTED")
                return [
                    {
                        "event": "flatten",
                        "symbol": symbol,
                        "state": "IDLE",
                        "action": None if action is None else action.action,
                    }
                ]
            if kind == "bar_close":
                bar = event.get("bar")
                if not isinstance(bar, Bar):
                    raise ValueError("bar_close needs a Bar")
                return self.on_bar_close(bar)
            raise ValueError(f"unknown desk event: {kind!r}")
        if event.stream == "trades":
            return self.on_trade(event, zones or [])
        st = self.state_for(event.symbol)
        if event.stream in {"book_diff", "bbo", "snapshot"}:
            self._apply_book_event(st, event)
            return [{"event": event.stream, "symbol": event.symbol}]
        if event.stream in {"funding", "oi", "mark"}:
            # Recorder emits these. There is no OI-peak / funding-rank atom on the desk.
            # Do not pretend a journal row was written.
            return [{"event": event.stream, "symbol": event.symbol}]
        if event.stream in {"gap", "resync"}:
            st.book = Book(tick_size=str(self.tick_size))
            return [{"event": event.stream, "symbol": event.symbol, "book_dirty": True}]
        raise ValueError(f"unknown stream: {event.stream!r}")

    def on_bar_close(self, bar: Bar) -> list[dict[str, Any]]:
        st = self.state_for(bar.symbol)
        st.bars.append(bar)
        if bar.symbol == "BTCUSDT":
            self.btc.bars.append(bar)
            self._publish_btc_bus(st, bar)
        if bar.tf in {self.config.htf, self.config.htf_d1}:
            self.publish_card(bar.symbol, bar.close_ts)
        if st.last_touch is None:
            return []
        if bar.tf != self.config.working_tf:
            return []
        # Plan: LABEL_ZLG (8s) then CAV on a closed bar, then JURY.
        # A working bar can close inside the 8s window — wait for the tick.
        if st.state != "LABEL_ZLG":
            return []
        return self._eval_cav_and_jury(st, bar)

    def publish_card(self, symbol: str, now: datetime) -> CardLive:
        """Compute B labels and write claim b_card:SYMBOL. Never sends."""
        bars = self.state_for(symbol).bars
        vol = volume_snapshot(bars)
        card = card_from_news(
            symbol=symbol,
            now=now,
            calendar=self.calendar,
            volume=vol,
            bars=bars,
        )
        self.knowledge.put_card_live(symbol, card.to_payload())
        return card

    def _publish_btc_bus(self, st: SymbolState, bar: Bar) -> None:
        """BTC symbol loop writes the alt bus. Unknown HTF stays None."""
        closed_at = bar.close_ts + timedelta(microseconds=1)
        news_at = us_data_known_at(closed_at, self.calendar)
        label = self.btc_regime.classify(
            closed_at,
            symbol="BTCUSDT",
            bars=st.bars,
            news_known_at=news_at,
        )
        # Last non-None label is not today's fact. Unknown HTF / quiet day → None.
        self.btc.regime = label
        if bar.tf != self.config.working_tf:
            return
        self.btc.broke_support = False
        self.btc.broke_resistance = False
        for zone in self.registry._zones.values():
            if zone.symbol != "BTCUSDT":
                continue
            # 2.9.2: eaten is the 8s touch in *this* bar. A stale print is not this close.
            eaten = any(
                touch.zone_id == zone.zone_id
                and touch.tape_eaten
                and bar.open_ts <= touch.ts < bar.close_ts
                for touch in self.registry.touches
            )
            if not Break.detect(zone=zone, bar=bar, tape_eaten=eaten, t=closed_at):
                continue
            if zone.side == "support":
                self.btc.broke_support = True
            else:
                self.btc.broke_resistance = True

    def on_trade(self, trade: MarketEvent, zones: list[Zone]) -> list[dict[str, Any]]:
        require_utc(trade.exchange_ts)
        st = self.state_for(trade.symbol)
        st.trades.append(trade)
        try:
            px = Decimal(str(trade.payload["px"]))
            if px > 0:
                self.last_price[trade.symbol] = px
                if self.knowledge.available():
                    self.knowledge.put_last_price(trade.symbol, str(px))
        except (KeyError, ArithmeticError):
            pass
        if zones:
            self.persist_zones(zones)
        if st.book.ready:
            self._wall_for(st.symbol).on_book_and_trade(
                st.book, trade, ts=trade.exchange_ts
            )
        opened = self.registry.on_trade(trade, zones)
        if not opened:
            return []
        # Registry may open several zones on one print. The desk is one
        # 8s clock per symbol — do not steal an armed window for a later zone.
        if st.last_touch is not None and st.state != "IDLE":
            return []
        touch = opened[0]
        st.last_touch = touch
        st.adds.clear()
        if st.book.ready:
            st.book_pre = st.book.snapshot_copy()
        st.state = "ARM_ZLG"
        st.armed_at = trade.exchange_ts
        return [{"event": "armed", "touch_id": touch.touch_id, "symbol": trade.symbol}]

    def tick(self, now: datetime) -> list[dict[str, Any]]:
        when = require_utc(now)
        out = self._settle_shadows(when)
        window = timedelta(seconds=self.config.zlg_window_s)
        for st in self.symbols.values():
            if st.state != "ARM_ZLG" or st.armed_at is None or st.last_touch is None:
                continue
            if when < st.armed_at + window:
                continue
            out.extend(self._label_zlg(st, when))
        return out

    def _settle_shadows(self, now: datetime) -> list[dict[str, Any]]:
        """24/7: close pending touches and score shadow R. No orders."""
        events: list[dict[str, Any]] = []
        days: set[str] = set()
        pending_symbols: set[str] = set()
        for touch in self.registry.touches:
            if touch.outcome != "pending":
                continue
            try:
                pending_symbols.add(self.registry.zone(touch.zone_id).symbol)
            except KeyError:
                continue
        for symbol in pending_symbols:
            st = self.state_for(symbol)
            px = self.last_price.get(symbol)
            if px is None:
                armed = st.last_touch
                px = None if armed is None else armed.trade_px
            if px is None:
                continue
            changed = self.registry.resolve_symbol(
                symbol, now=now, bars=st.bars, last_px=px
            )
            for touch in changed:
                events.append(
                    {
                        "event": "shadow_outcome",
                        "touch_id": touch.touch_id,
                        "outcome": touch.outcome,
                    }
                )
                row = self.knowledge.get_journal_touch(touch.touch_id)
                if row is None:
                    continue
                row["outcome"] = touch.outcome
                day = row_day_utc(row)
                if day:
                    days.add(day)
                self.knowledge.put_journal_touch(touch.touch_id, row)
        for day in days:
            persist_day(self.knowledge, day)
        return events

    def _label_zlg(self, st: SymbolState, now: datetime) -> list[dict[str, Any]]:
        touch = st.last_touch
        if touch is None:
            return []
        zone = self.registry.zone(touch.zone_id)
        if touch.btc_regime is None and self.btc.regime:
            # Bus is already published. Stamp before B-gate so a CPI veto
            # does not leave the touch without the regime we already know.
            self.registry.fill_btc(regime=self.btc.regime, touch_id=touch.touch_id)
            touch = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
            st.last_touch = touch
        card = self._card_for(st.symbol, now)
        gated = self._b_gate(st, touch, zone, card)
        if gated is not None:
            return gated
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
            book_ready=book.ready,
        )
        self.registry.fill_gesture(gesture=result.gesture, touch_id=touch.touch_id)
        self.registry._patch(
            touch_id=touch.touch_id,
            overwrite=True,
            a_same=str(result.a_same),
            a_back=str(result.a_back),
            a_in=str(result.a_in),
            a_opp=str(result.a_opp),
        )
        if book.ready:
            self.registry.fill_tape(
                book_pre=book, trades=st.trades, touch_id=touch.touch_id
            )
        self._stamp_touch_interval(st, touch)
        st.state = "LABEL_ZLG"
        out = [{"event": "zlg", "touch_id": touch.touch_id, "gesture": result.gesture}]
        work = [
            bar
            for bar in st.bars
            if bar.tf == self.config.working_tf and bar.close_ts >= touch.ts
        ]
        work.sort(key=lambda bar: bar.close_ts)
        if work:
            # First closed working bar after the print, not the latest leftover.
            out.extend(self._eval_cav_and_jury(st, work[0]))
        return out

    def _card_for(self, symbol: str, now: datetime) -> CardLive | None:
        raw = self.knowledge.get_card_live(symbol)
        if raw is not None:
            try:
                stored = CardLive.from_payload(raw)
            except (ValueError, KeyError, TypeError):
                stored = None
            if stored is not None and card_is_fresh(stored, symbol=symbol, now=now):
                return stored
        if not self.calendar:
            return None
        return self.publish_card(symbol, now)

    def _b_gate(
        self,
        st: SymbolState,
        touch: Touch,
        zone: Zone,
        card: CardLive | None,
    ) -> list[dict[str, Any]] | None:
        """veto / hold / red marks stop ZLG and CAV. Same law as observe()."""
        if card is None:
            return None
        if card.bearing_verdict == "veto":
            return self._b_veto_touch(st, touch, zone, card)
        if card.bearing_verdict == "hold":
            return self._b_hold_touch(st, touch, zone, card)
        if card.bearing_verdict in {"propose", "cut_size"} and not card.context_ok():
            return self._b_split_touch(st, touch, zone, card)
        return None

    def _b_veto_touch(
        self,
        st: SymbolState,
        touch: Touch,
        zone: Zone,
        card: CardLive,
    ) -> list[dict[str, Any]]:
        self.registry._patch(
            touch_id=touch.touch_id,
            overwrite=True,
            bearing_verdict="veto",
            jury="VETO",
            skip_reason="b_veto",
            card_id=card.card_id,
            fib_trend=card.fib_zone,
            fvg_present=card.fvg_status == "filled",
            sweep_wick=card.sweep_status == "done",
            gex_bg=card.gex_bg,
            poc=card.volume.poc,
            vah=card.volume.vah,
            val=card.volume.val,
            ob_status=card.ob_status,
            bos_status=card.bos_status,
        )
        action = self.manager.on_refute(load_bearing=True, verdict="veto")
        line = touch_line(symbol=st.symbol, card=card, jury="VETO")
        self._write_b_journal(touch, zone, card, jury="VETO", skip="b_veto", line=line)
        st.state = "IDLE"
        st.last_touch = None
        return [
            {
                "event": "jury",
                "touch_id": touch.touch_id,
                "jury": "VETO",
                "sent": False,
                "touch_line": line,
                "action": None if action is None else action.action,
            }
        ]

    def _b_hold_touch(
        self,
        st: SymbolState,
        touch: Touch,
        zone: Zone,
        card: CardLive,
    ) -> list[dict[str, Any]]:
        self.registry._patch(
            touch_id=touch.touch_id,
            overwrite=True,
            bearing_verdict="hold",
            jury="SILENCE",
            skip_reason="b_hold",
            card_id=card.card_id,
            fib_trend=card.fib_zone,
            fvg_present=card.fvg_status == "filled",
            sweep_wick=card.sweep_status == "done",
            gex_bg=card.gex_bg,
            ob_status=card.ob_status,
            bos_status=card.bos_status,
        )
        line = touch_line(symbol=st.symbol, card=card, jury="SILENCE")
        self._write_b_journal(touch, zone, card, jury="SILENCE", skip="b_hold", line=line)
        st.state = "IDLE"
        st.last_touch = None
        return [
            {
                "event": "jury",
                "touch_id": touch.touch_id,
                "jury": "SILENCE",
                "sent": False,
                "touch_line": line,
            }
        ]

    def _b_split_touch(
        self,
        st: SymbolState,
        touch: Touch,
        zone: Zone,
        card: CardLive,
    ) -> list[dict[str, Any]]:
        self.registry._patch(
            touch_id=touch.touch_id,
            overwrite=True,
            bearing_verdict=card.card_voice(),
            jury="SPLIT",
            skip_reason="b_marks",
            card_id=card.card_id,
            fib_trend=card.fib_zone,
            fvg_present=card.fvg_status == "filled",
            sweep_wick=card.sweep_status == "done",
            gex_bg=card.gex_bg,
            ob_status=card.ob_status,
            bos_status=card.bos_status,
        )
        line = touch_line(symbol=st.symbol, card=card, jury="SPLIT")
        self._write_b_journal(touch, zone, card, jury="SPLIT", skip="b_marks", line=line)
        st.state = "IDLE"
        st.last_touch = None
        return [
            {
                "event": "jury",
                "touch_id": touch.touch_id,
                "jury": "SPLIT",
                "sent": False,
                "touch_line": line,
            }
        ]

    def _write_b_journal(
        self,
        touch: Touch,
        zone: Zone,
        card: CardLive,
        *,
        jury: str,
        skip: str,
        line: str,
    ) -> None:
        journal = empty_journal()
        journal.update(
            {
                "zone_id": touch.zone_id,
                "touch_ts": touch.ts.isoformat(),
                "trade_px": str(touch.trade_px),
                "trade_qty": str(touch.trade_qty),
                "session_name": session_name(touch.ts),
                "session_hour_utc": touch.ts.hour,
                "poc": card.volume.poc,
                "vah": card.volume.vah,
                "val": card.volume.val,
                "fib_trend": card.fib_zone,
                "fib_in_05_1": card.fib_zone in {"OTE", "in_05_1"},
                "fib_in_ote_gold": card.fib_zone == "OTE",
                "rsi_tf": "htf",
                "rsi_value": card.rsi_htf,
                "fvg_present": card.fvg_status == "filled",
                "sweep_wick": card.sweep_status == "done",
                "gex_bg": card.gex_bg,
                "cav_label": touch.cav_label,
                "zlg_label": touch.gesture,
                "jury": jury,
                "bearing_verdict": card.card_voice(),
                "card_id": card.card_id,
                "skip_reason": skip,
                "shadow_would": False,
                "challenger_would": False,
                "challenger_tag": None,
            }
        )
        self.knowledge.put_journal_touch(
            touch.touch_id,
            {
                **journal,
                "touch_id": touch.touch_id,
                "symbol": zone.symbol,
                "touch_line": line,
                "ob_status": card.ob_status,
                "bos_status": card.bos_status,
            },
        )
        day = row_day_utc(journal)
        if day:
            persist_day(self.knowledge, day)

    def _eval_cav_and_jury(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        touch = st.last_touch
        if touch is None:
            return []
        zone = self.registry.zone(touch.zone_id)
        card = self._card_for(st.symbol, bar.close_ts)
        gated = self._b_gate(st, touch, zone, card)
        if gated is not None:
            return gated
        if bar.close_ts < touch.ts:
            return []
        # Atom requires close_ts < t. Plan: CAV only on a closed bar (close_ts ≤ now).
        closed_at = bar.close_ts + timedelta(microseconds=1)
        h4 = self.zones_map.htf_bias(st.symbol, closed_at, st.bars)
        d1 = self.zones_map.htf_d1_bias(st.symbol, closed_at, st.bars)
        bounce_side = "long" if zone.side == "support" else "short"
        htf = h4
        if d1 not in {"unknown", "box"} and d1 != bounce_side:
            htf = d1
        elif h4 not in {"unknown", "box"} and h4 != bounce_side:
            htf = h4
        cav = cav_label(zone, bar, t=closed_at, htf_bias=htf, closed_bars=st.bars)
        known_zones = tuple(
            z for z in self.registry._zones.values() if z.symbol == st.symbol
        ) or (zone,)
        if in_mid_range(
            bar.close,
            known_zones,
            tick=self.tick_size,
            band_ticks=self.config.mid_band_ticks,
        ):
            cav = "NOISE"
        self.registry.fill_cav(cav_label=cav, touch_id=touch.touch_id)
        live = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
        idea = "bounce"
        tag = FailedBreak.tag(zone=zone, bar=bar)
        if tag:
            idea = "failed_break"
        elif live.cav_label == "THROUGH":
            idea = "breakout"
        if live.btc_regime is None and self.btc.regime:
            # Published bus only. Alt H4 is not BTC; BTC already wrote the bus
            # on this close (on_bar_close publishes before jury).
            self.registry.fill_btc(regime=self.btc.regime, touch_id=touch.touch_id)
        n_cav = sum(
            1
            for hist in self.registry.touches
            if hist.cav_label == live.cav_label and self._same_symbol(hist, st.symbol)
        )
        n_zlg = sum(
            1
            for row in self.registry.touches
            if row.gesture == live.gesture and self._same_symbol(row, st.symbol)
        )
        idea_side = "buy" if zone.side == "support" else "sell"
        if idea == "failed_break":
            idea_side = "sell" if zone.side == "support" else "buy"
        if idea == "breakout":
            idea_side = "sell" if zone.side == "support" else "buy"
        # 2.9.3: long vs BTC support break; short vs BTC resistance break.
        break_against = False
        if st.symbol != "BTCUSDT":
            break_against = (
                self.btc.broke_support
                if idea_side == "buy"
                else self.btc.broke_resistance
            )
        # BtcRegime writes trend|box|news. long/short never land on the bus.
        # BTCUSDT is not "same side" without a box label — that was a rubber stamp.
        btc_same_side = self.btc.regime == "box"
        cpi_window = cpi_day(closed_at, self.calendar)
        wall_since, wall_until = self._wall_bounds(touch)
        wall_events = self.walls[st.symbol].events if st.symbol in self.walls else ()
        silent_wall = pulled_without_print(
            wall_events, since=wall_since, until=wall_until
        )
        if card is not None and live.bearing_verdict is None:
            self.registry._patch(
                touch_id=touch.touch_id,
                overwrite=True,
                bearing_verdict=card.card_voice(),
                card_id=card.card_id,
                fib_trend=card.fib_zone,
                fib_in_05_1=card.fib_zone in {"OTE", "in_05_1"},
                fib_in_ote_gold=card.fib_zone == "OTE",
                rsi_value=card.rsi_htf,
                fvg_present=card.fvg_status == "filled",
                sweep_wick=card.sweep_status == "done",
                gex_bg=card.gex_bg,
                poc=card.volume.poc,
                vah=card.volume.vah,
                val=card.volume.val,
                wall_state=card.volume.walls,
                ob_status=card.ob_status,
                bos_status=card.bos_status,
            )
            live = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
        card_wall_pulled = bool(card is not None and card.volume.walls == "pulled")
        wall_no_print = silent_wall or card_wall_pulled
        stamped = self.registry.stamp_jury(
            idea=idea,
            n_cav=n_cav,
            n_zlg=n_zlg,
            touch_id=touch.touch_id,
            wall_no_print=wall_no_print,
            btc_break_against=break_against,
            card_bearing_verdict=live.bearing_verdict,
            cpi_window=cpi_window,
            trades_in_window=live.trades_in_window,
            btc_same_side=btc_same_side,
        )
        row = stamped[0] if stamped else live
        first = resolve_first_fact(row.gesture, n_zlg)
        self._stamp_journal_atoms(st, bar, zone, row, closed_at)
        row = next(t for t in self.registry.touches if t.touch_id == row.touch_id)
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
            card_bearing_verdict=row.bearing_verdict,
            wall_no_print=wall_no_print,
            btc_break_against=break_against,
            trades_in_window=row.trades_in_window,
            btc_same_side=btc_same_side,
            cpi_window=cpi_window,
        )
        jury = decide(voices)
        picture = picture_for(idea)
        card_id = None if card is None else card.card_id
        if card_id is None:
            if needs_new_card(idea) or st.symbol not in self.open_card_id:
                card_id = str(uuid4())
                self.open_card_id[st.symbol] = card_id
            else:
                card_id = self.open_card_id[st.symbol]
        else:
            self.open_card_id[st.symbol] = card_id
        self._persist_card(card_id, idea, st.symbol, row.ts)
        mid = in_mid_range(
            row.trade_px,
            known_zones,
            tick=self.tick_size,
            band_ticks=self.config.mid_band_ticks,
        )
        has_tvh = tvh_ok(
            price_in_zone=price_in_zone(row.trade_px, zone),
            mid=mid,
            cav=row.cav_label,
            zlg=row.gesture,
            n_cav=n_cav,
            n_zlg=n_zlg,
            tape_eaten=row.tape_eaten,
        )
        shadow_would = jury == "ACCORD"
        skip: str | None
        if not has_tvh:
            shadow_would = False
            skip = NO_TVH
        elif shadow_would:
            skip = None
        else:
            skip = first.tag if first.tag == "shadow_gesture" else jury
        if idea == "breakout" and not breakout_enabled() and skip is None:
            skip = "breakout_off"
        shadow_side = idea_side if shadow_would else None
        if shadow_would:
            shadow_tag = "bounce" if idea == "bounce" else (
                "failed_break_bounce" if idea == "failed_break" else "breakout"
            )
        else:
            shadow_tag = None
        self.registry._patch(
            touch_id=row.touch_id,
            overwrite=True,
            skip_reason=skip,
            jury=jury,
            idea=idea,
            shadow_would=shadow_would,
            shadow_side=shadow_side,
            shadow_tag=shadow_tag,
            first_fact=first.first_fact,
            n_cav=n_cav,
            n_zlg=n_zlg,
            card_id=card_id,
            htf_h4=h4,
            htf_d1=d1,
            cav_tf=zone.tf,
            btc_break_against=break_against,
            btc_state=row.btc_regime,
            session_name=session_name(row.ts),
        )
        row = next(t for t in self.registry.touches if t.touch_id == row.touch_id)
        journal = empty_journal()
        journal.update(
            {
                "zone_id": row.zone_id,
                "touch_ts": row.ts.isoformat(),
                "trade_px": str(row.trade_px),
                "trade_qty": str(row.trade_qty),
                "session_name": row.session_name or session_name(row.ts),
                "session_hour_utc": (
                    row.session_hour
                    if row.session_hour is not None
                    else require_utc(row.ts).hour
                ),
                "prior_session_hi": row.prior_session_hi,
                "prior_session_lo": row.prior_session_lo,
                "poc": row.poc,
                "vah": row.vah,
                "val": row.val,
                "fib_trend": row.fib_trend,
                "fib_in_05_1": row.fib_in_05_1,
                "fib_in_ote_gold": row.fib_in_ote_gold,
                "rsi_tf": row.rsi_tf,
                "rsi_value": row.rsi_value,
                "fvg_present": row.fvg_present,
                "sweep_wick": row.sweep_wick,
                "htf_h4": row.htf_h4,
                "htf_d1": row.htf_d1,
                "cav_label": row.cav_label,
                "cav_tf": row.cav_tf or zone.tf,
                "bar_quality": row.bar_quality,
                "w_now": None if row.w_now is None else str(row.w_now),
                "w_rank": None if row.w_rank is None else str(row.w_rank),
                "zlg_label": row.gesture,
                "A_same": row.a_same,
                "A_back": row.a_back,
                "A_in": row.a_in,
                "A_opp": row.a_opp,
                "tape_eaten": row.tape_eaten,
                "ofi": row.ofi,
                "trades_in_window": row.trades_in_window,
                "wall_state": row.wall_state,
                "refill_proxy": row.refill_proxy,
                "prs_tau": row.prs_tau,
                "prs_y": None if row.prs_y is None else str(row.prs_y),
                "gex_bg": row.gex_bg,
                "btc_state": row.btc_state or row.btc_regime,
                "btc_break_against": row.btc_break_against,
                "card_id": row.card_id,
                "bearing_verdict": row.bearing_verdict,
                "first_fact": row.first_fact,
                "n_cav": row.n_cav,
                "n_zlg": row.n_zlg,
                "jury": row.jury,
                "shadow_would": row.shadow_would,
                "shadow_side": row.shadow_side,
                "shadow_tag": row.shadow_tag,
                "challenger_would": False,
                "challenger_tag": None,
                "skip_reason": row.skip_reason,
                "outcome": row.outcome,
                "rho_class_id": row.rho_class_id,
            }
        )
        missing = [key for key in JOURNAL_KEYS if key not in journal]
        if missing:
            raise RuntimeError(f"journal missing {missing}")
        imb = None
        book = st.book_pre or st.book
        if book.ready:
            imb = book.imbalance(5)
        line = touch_line(symbol=st.symbol, card=card, jury=jury)
        eaten_qty = None
        if book.ready:
            try:
                eaten_qty = str(
                    self.tape.eaten_qty(
                        book=book,
                        trades=st.trades,
                        zone=zone,
                        t0=row.ts,
                        tick_size=self.tick_size,
                        config=self.config,
                    )
                )
            except ValueError:
                eaten_qty = None
        extra = {
            "touch_id": row.touch_id,
            "symbol": st.symbol,
            "idea": row.idea or idea,
            "picture": picture,
            "imbalance": None if imb is None else str(imb),
            "touch_line": line,
            "macro_multiplier": None if card is None else str(card.macro_multiplier),
            "ob_status": None if card is None else card.ob_status,
            "bos_status": None if card is None else card.bos_status,
            "tape_eaten_qty": eaten_qty,
        }
        payload_row = {**journal, **extra}
        payload_row["challenger_would"] = challenger_on(payload_row)
        payload_row["challenger_tag"] = challenger_tag(payload_row)
        self.knowledge.put_journal_touch(row.touch_id, payload_row)
        day = row_day_utc(payload_row)
        if day:
            persist_day(self.knowledge, day)
        payload = {
            "touch_id": row.touch_id,
            "jury": jury,
            "shadow_would": shadow_would,
            "challenger_would": payload_row["challenger_would"],
        }
        self.shadow_writes.append(self.shadow.write(payload))
        sent = False
        if (
            shadow_would
            and skip is None
            and self.user_mode in {"demo", "live"}
            and self.hello_ok()
            and book.ready
            and in_desk_window(closed_at)
            and self.session.allows(closed_at, self.calendar)[0]
        ):
            spr = book.spread()
            bid, ask = book.best()
            mid_px = (bid + ask) / 2 if bid is not None and ask is not None else None
            if spr is not None and mid_px is not None and mid_px > 0:
                snap = BounceSnapshot(
                    now=closed_at,
                    symbol=st.symbol,
                    price=row.trade_px,
                    tick=self.tick_size,
                    trading_mode=self.user_mode,
                    zone=zone,
                    zones=known_zones,
                    next_target=opposing_target(
                        known_zones,
                        side=idea_side,
                        entry=row.trade_px,
                        symbol=st.symbol,
                    ),
                    spread_frac=spr / mid_px,
                    calendar=self.calendar,
                    unlock_today=self.unlocks.team_today(st.symbol, closed_at),
                    unlock_tomorrow=self.unlocks.team_tomorrow(st.symbol, closed_at),
                    idea=idea,
                    jury=jury,
                    cav_label=row.cav_label,
                    zlg_label=row.gesture,
                    n_cav=n_cav,
                    n_zlg=n_zlg,
                    tape_eaten=row.tape_eaten,
                    wall_no_print=wall_no_print,
                    prs_y=row.prs_y,
                    btc_regime=row.btc_regime,
                    btc_broke=break_against,
                    btc_zone_side="support" if idea_side == "buy" else "resistance",
                    btc_same_side=btc_same_side,
                    gesture_n=n_zlg,
                    trades_in_window=row.trades_in_window,
                    first_minute=(
                        self.first_minute.blocks(closed_at, bar.close_ts)
                        if idea == "breakout"
                        else False
                    ),
                    close_beyond=row.cav_label == "THROUGH",
                    allow_break=breakout_enabled(),
                    card_bearing_verdict=row.bearing_verdict,
                    b_verdict=None if card is None else card.bearing_verdict,
                    macro_multiplier=Decimal("1") if card is None else card.macro_multiplier,
                    b_marks_ok=True if card is None else card.context_ok(),
                    rvol=(
                        None
                        if card is None or not card.volume.rvol
                        else Decimal(card.volume.rvol)
                    ),
                    wall_state=None if card is None else card.volume.walls,
                    venue="perp" if card is None else card.venue,
                    spot_acked=False if card is None else self.spot.acked(st.symbol),
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
        return [
            {
                "event": "jury",
                "touch_id": row.touch_id,
                "jury": jury,
                "sent": sent,
                "touch_line": line,
            }
        ]

    def _stamp_journal_atoms(
        self,
        st: SymbolState,
        bar: Bar,
        zone: Zone,
        row: Touch,
        closed_at: datetime,
    ) -> None:
        """Fill journal-only voices. Does not change jury inputs already stamped."""
        quality = classify_bar_quality(st.bars, bar, t=closed_at)
        self.registry.fill_bar_quality(quality=quality, touch_id=row.touch_id)
        w_now = width_now_from_history(bar, st.bars, t=closed_at)
        w_rank = None
        if w_now is not None:
            w_rank = width_rank(
                zone_id=zone.zone_id,
                now=row.ts,
                w_now=w_now,
                history=self._width_history,
            )
            self._width_history.append(
                WidthSample(zone_id=zone.zone_id, ts=row.ts, w_now=w_now)
            )
        self.registry.fill_width(w_now=w_now, w_rank=w_rank, touch_id=row.touch_id)
        self.registry.fill_sweep_wick(
            flag=sweep_wick(zone=zone, bar=bar),
            touch_id=row.touch_id,
        )
        self.registry.fill_fvg_present(
            flag=fvg_present(
                st.bars,
                symbol=st.symbol,
                tf=bar.tf,
                close_ts=bar.close_ts,
            ),
            touch_id=row.touch_id,
        )
        self.registry.fill_session_hour(touch_id=row.touch_id)
        wall_since, wall_until = self._wall_bounds(row)
        events = self.walls.get(st.symbol).events if st.symbol in self.walls else []
        wall_state = last_wall_kind(events, since=wall_since, until=wall_until)
        self.registry._patch(
            touch_id=row.touch_id,
            overwrite=True,
            wall_state=wall_state,
        )

    def _wall_bounds(self, touch: Touch) -> tuple[datetime, datetime]:
        """Same 8s clock as ZLG/OFI, plus 8s before the print."""
        delta = timedelta(seconds=self.config.zlg_window_s)
        return touch.ts - delta, touch.ts + delta

    def _same_symbol(self, touch: Touch, symbol: str) -> bool:
        zone = self.registry._zones.get(touch.zone_id)
        return zone is not None and zone.symbol == symbol

    def _touch_window(
        self, st: SymbolState, touch: Touch, *, seconds: int
    ) -> tuple[list[MarketEvent], list[tuple[datetime, Book]]]:
        start = touch.ts
        end = start + timedelta(seconds=seconds)
        prints = [
            trade
            for trade in st.trades
            if trade.stream == "trades"
            and start <= require_utc(trade.exchange_ts) <= end
        ]
        books = [
            (ts, copy)
            for ts, copy in st.book_history
            if copy.ready and start <= ts <= end
        ]
        return prints, books

    def _stamp_touch_interval(self, st: SymbolState, touch: Touch) -> None:
        """OFI and PRS belong to the 8s touch window, not the last 8s before CAV."""
        prints, path = self._touch_window(st, touch, seconds=self.config.zlg_window_s)
        ofi_val = None
        books = [copy for _, copy in path]
        if len(books) >= 2:
            try:
                ofi_val = str(OFI().window(prints, books))
            except ValueError:
                ofi_val = None
        prs_tau = None
        src = next((trade for trade in prints if trade.exchange_ts == touch.ts), None)
        if src is not None and st.book_pre is not None and st.book_pre.ready:
            try:
                result = self._prs_for(st.symbol).compute(src, st.book_pre, path)
                self.registry.fill_prs(prs_y=result.Y, touch_id=touch.touch_id)
                prs_tau = str(result.tau)
            except ValueError:
                pass
        self.registry._patch(
            touch_id=touch.touch_id,
            overwrite=True,
            ofi=ofi_val,
            prs_tau=prs_tau,
        )

    def _persist_card(self, card_id: str, idea: str, symbol: str, when: datetime) -> None:
        if not self.knowledge.available():
            return
        card = pending_card(
            thesis=f"{idea} {symbol}",
            as_of=when,
            card_id=card_id,
            n_claims=5,
        )
        self.knowledge.put_claim(
            card_id,
            {
                "card_id": card_id,
                "symbol": symbol,
                "idea": idea,
                "thesis": card.thesis,
                "claims": [c.model_dump(mode="json") for c in card.claims],
            },
        )

    def play(
        self,
        events: Sequence[MarketEvent | dict[str, Any]],
        *,
        extra_zones: Sequence[Zone] = (),
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """One-pass organism: tape → touch → ZLG → CAV → jury → shadow → queue.

        No sleep. Clocks come from the events (and optional `now`). This is the
        live cycle the atoms already implement; play() is the only caller that
        walks a whole tape without `--serve`.
        """
        from capitalizator.desk.tape import close_due_bars, zones_for_trade

        out: list[dict[str, Any]] = []
        extras = tuple(extra_zones)

        def advance(when: datetime) -> None:
            # Plan: LABEL_ZLG (8s) then CAV on a closed bar, then JURY.
            # Catch-up `--once` lands both clocks in one now= — tick first.
            out.extend(self.tick(when))
            for symbol in _close_symbols(self.symbols):
                out.extend(close_due_bars(self, symbol, when))

        for event in _ordered_events(events):
            if isinstance(event, dict):
                kind = str(event.get("kind") or event.get("stream") or "")
                if kind == "bar_close":
                    bar = event.get("bar")
                    if isinstance(bar, Bar):
                        advance(bar.close_ts)
                out.extend(self.on_event(event, list(extras) or None))
                continue
            advance(event.exchange_ts)
            if event.stream == "trades":
                built = zones_for_trade(self, event, extras)
                self.persist_zones(built)
                out.extend(self.on_event(event, built))
            else:
                out.extend(self.on_event(event))
        if now is not None:
            advance(require_utc(now))
        return out


def _close_symbols(symbols: dict[str, SymbolState]) -> list[str]:
    """BTC writes the alt bus. Close it first when several bars share `now`."""
    return sorted(symbols, key=lambda name: (name != "BTCUSDT", name))


_STREAM_RANK = {
    "snapshot": 0,
    "book_diff": 1,
    "bbo": 2,
    "funding": 3,
    "oi": 4,
    "mark": 5,
    "gap": 6,
    "resync": 7,
    "trades": 8,
}


def _ordered_events(
    events: Sequence[MarketEvent | dict[str, Any]],
) -> list[MarketEvent | dict[str, Any]]:
    """Stable time order. Snapshot before diffs before prints at the same ts."""

    def key(event: MarketEvent | dict[str, Any]) -> tuple[datetime, int, str]:
        if isinstance(event, dict):
            bar = event.get("bar")
            ts = bar.close_ts if isinstance(bar, Bar) else datetime.min.replace(tzinfo=UTC)
            return (ts, 9, str(event.get("kind") or event.get("stream") or ""))
        return (event.exchange_ts, _STREAM_RANK.get(event.stream, 9), event.symbol)

    return sorted(events, key=key)


def _level_sizes(book: Book) -> dict[tuple[str, Decimal], Decimal]:
    out: dict[tuple[str, Decimal], Decimal] = {}
    for side in ("bid", "ask"):
        for px, sz in book.levels(side).items():
            out[(side, px)] = sz
    return out


def _record_adds(
    st: SymbolState,
    ts: datetime,
    before: dict[tuple[str, Decimal], Decimal],
) -> None:
    """Positive size deltas after a diff are ZLG BookAdds. Pulls are not adds."""
    for side in ("bid", "ask"):
        for px, sz in st.book.levels(side).items():
            delta = sz - before.get((side, px), Decimal("0"))
            if delta > 0:
                hit: Literal["bid", "ask"] = "bid" if side == "bid" else "ask"
                st.adds.append(BookAdd(ts=ts, side=hit, px=px, qty=delta))


def _levels(rows: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(rows, list | tuple):
        return ()
    out: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        out.append((str(row[0]), str(row[1])))
    return tuple(out)

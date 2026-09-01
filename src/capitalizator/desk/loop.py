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
from capitalizator.btc.break_def import Break
from capitalizator.btc.regime import BtcRegime
from capitalizator.btc.veto import BtcVeto
from capitalizator.card.build import from_news as card_from_news
from capitalizator.card.first_fact import resolve as resolve_first_fact
from capitalizator.card.live import CardLive, touch_line
from capitalizator.card.volume import snapshot as volume_snapshot
from capitalizator.desk.pictures import needs_new_card, picture_for
from capitalizator.desk.session_name import session_name
from capitalizator.exec.failed_break import FailedBreak
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.exec.manage import TradeManager
from capitalizator.exec.shadow import ShadowWriter
from capitalizator.exec.spot import SpotAdapter
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy, in_mid_range
from capitalizator.jury.desk import (
    decide,
    voices_for_bounce,
    voices_for_breakout,
    voices_for_failed_break,
)
from capitalizator.memory.journal import JOURNAL_KEYS, empty_journal
from capitalizator.memory.registry import Registry, Touch
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.product import DEFAULT_MODE, META_HELLO
from capitalizator.patterns.cav import label as cav_label
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rest_snapshot import BookSnapshot
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
        self.btc_regime = BtcRegime(self.zones_map)
        self.manager = TradeManager()
        self.spot = SpotAdapter(knowledge)
        self.shadow_writes: list[dict[str, Any]] = []

    def state_for(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(
                symbol=symbol, book=Book(tick_size=str(self.tick_size))
            )
        return self.symbols[symbol]

    def hello_ok(self) -> bool:
        return self.knowledge.meta(META_HELLO) == "1"

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
            return [{"event": event.stream, "symbol": event.symbol, "journal": True}]
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
        if st.last_touch is None:
            return []
        if bar.tf != self.config.working_tf:
            return []
        return self._eval_cav_and_jury(st, bar)

    def _publish_btc_bus(self, st: SymbolState, bar: Bar) -> None:
        """BTC symbol loop writes the alt bus. Unknown HTF stays None."""
        closed_at = bar.close_ts + timedelta(microseconds=1)
        news_at = None
        for row in self.calendar:
            if row.known_at <= closed_at:
                news_at = row.known_at
                break
        label = self.btc_regime.classify(
            closed_at,
            symbol="BTCUSDT",
            bars=st.bars,
            news_known_at=news_at,
        )
        if label is not None:
            self.btc.regime = label
        if bar.tf != self.config.working_tf:
            return
        self.btc.broke_support = False
        self.btc.broke_resistance = False
        for zone in self.registry._zones.values():
            if zone.symbol != "BTCUSDT":
                continue
            eaten = any(
                touch.zone_id == zone.zone_id and touch.tape_eaten
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
        opened = self.registry.on_trade(trade, zones)
        if not opened:
            return []
        touch = opened[-1]
        st.last_touch = touch
        st.adds.clear()
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
        st.state = "LABEL_ZLG"
        return [{"event": "zlg", "touch_id": touch.touch_id, "gesture": result.gesture}]

    def _card_for(self, symbol: str, now: datetime) -> CardLive | None:
        raw = self.knowledge.get_card_live(symbol)
        if raw is not None:
            return CardLive.from_payload(raw)
        if not self.calendar:
            return None
        vol = volume_snapshot(self.state_for(symbol).bars)
        return card_from_news(symbol=symbol, now=now, calendar=self.calendar, volume=vol)

    def _b_veto_touch(
        self,
        st: SymbolState,
        touch: Touch,
        zone: Zone,
        bar: Bar,
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

    def _b_split_touch(
        self,
        st: SymbolState,
        touch: Touch,
        zone: Zone,
        bar: Bar,
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
            }
        )
        self.knowledge.put_journal_touch(
            touch.touch_id,
            {
                **journal,
                "touch_id": touch.touch_id,
                "symbol": zone.symbol,
                "touch_line": line,
            },
        )

    def _eval_cav_and_jury(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        touch = st.last_touch
        if touch is None:
            return []
        zone = self.registry.zone(touch.zone_id)
        card = self._card_for(st.symbol, bar.close_ts)
        if card is not None and card.bearing_verdict == "veto":
            return self._b_veto_touch(st, touch, zone, bar, card)
        if (
            card is not None
            and card.bearing_verdict in {"propose", "cut_size"}
            and not card.context_ok()
        ):
            return self._b_split_touch(st, touch, zone, bar, card)
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
        known_zones = tuple(self.registry._zones.values()) if self.registry._zones else (zone,)
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
        n_cav = sum(
            1
            for row in self.registry.touches
            if row.cav_label == cav and self.registry.zone(row.zone_id).symbol == st.symbol
        )
        n_zlg = sum(
            1
            for row in self.registry.touches
            if row.gesture == live.gesture
            and self.registry.zone(row.zone_id).symbol == st.symbol
        )
        break_against = (
            self.btc.broke_resistance if idea == "breakout" else self.btc.broke_support
        )
        if st.symbol == "BTCUSDT":
            break_against = False
        idea_side = "buy" if zone.side == "support" else "sell"
        if idea == "failed_break":
            idea_side = "sell" if zone.side == "support" else "buy"
        if idea == "breakout":
            idea_side = "sell" if zone.side == "support" else "buy"
        btc_same_side = (
            (idea_side == "buy" and self.btc.regime in {"long", "box"})
            or (idea_side == "sell" and self.btc.regime in {"short", "box"})
        )
        if st.symbol == "BTCUSDT":
            btc_same_side = True
        cpi_window = any(
            row.event_class == "CPI" and row.event_time.date() == bar.close_ts.date()
            for row in self.calendar
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
            )
            live = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
        wall_no_print = (card.volume.walls == "pulled") if card is not None else False
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
        if card is not None and card.bearing_verdict == "hold":
            jury = "SILENCE"
        picture = picture_for(idea)
        card_id = str(uuid4()) if needs_new_card(idea) else None
        shadow_would = jury == "ACCORD"
        shadow_side = None
        shadow_tag = None
        if shadow_would:
            shadow_side = "buy" if zone.side == "support" else "sell"
            if idea == "failed_break":
                shadow_side = "sell" if zone.side == "support" else "buy"
            shadow_tag = "bounce" if idea == "bounce" else (
                "failed_break_bounce" if idea == "failed_break" else "breakout"
            )
        journal = empty_journal()
        journal.update(
            {
                "zone_id": row.zone_id,
                "touch_ts": row.ts.isoformat(),
                "trade_px": str(row.trade_px),
                "trade_qty": str(row.trade_qty),
                "session_name": session_name(row.ts),
                "session_hour_utc": row.ts.hour,
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
                "htf_h4": h4,
                "htf_d1": d1,
                "cav_label": row.cav_label,
                "cav_tf": zone.tf,
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
                "btc_state": row.btc_regime,
                "btc_break_against": break_against,
                "card_id": card_id,
                "bearing_verdict": row.bearing_verdict,
                "first_fact": first.first_fact,
                "n_cav": n_cav,
                "n_zlg": n_zlg,
                "jury": jury,
                "shadow_would": shadow_would,
                "shadow_side": shadow_side,
                "shadow_tag": shadow_tag,
                "skip_reason": None
                if shadow_would
                else (first.tag if first.tag == "shadow_gesture" else jury),
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
        extra = {
            "touch_id": row.touch_id,
            "symbol": st.symbol,
            "idea": idea,
            "picture": picture,
            "imbalance": None if imb is None else str(imb),
            "touch_line": line,
            "macro_multiplier": None if card is None else str(card.macro_multiplier),
        }
        self.knowledge.put_journal_touch(row.touch_id, {**journal, **extra})
        payload = {"touch_id": row.touch_id, "jury": jury, "shadow_would": shadow_would}
        self.shadow_writes.append(self.shadow.write(payload))
        sent = False
        if (
            shadow_would
            and self.user_mode in {"demo", "live"}
            and self.hello_ok()
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
                btc_same_side=btc_same_side,
                gesture_n=n_zlg,
                first_minute=(
                    self.first_minute.blocks(row.ts, bar.close_ts)
                    if idea == "breakout"
                    else False
                ),
                close_beyond=cav == "THROUGH",
                card_bearing_verdict=row.bearing_verdict,
                b_verdict=None if card is None else card.bearing_verdict,
                macro_multiplier=Decimal("1") if card is None else card.macro_multiplier,
                b_marks_ok=True if card is None else card.context_ok(),
                rvol=None
                if card is None or not card.volume.rvol
                else Decimal(card.volume.rvol),
                wall_state=None if card is None else card.volume.walls,
                wall_no_print=wall_no_print,
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
            for symbol in list(self.symbols):
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
                out.extend(self.on_event(event, zones_for_trade(self, event, extras)))
            else:
                out.extend(self.on_event(event))
        if now is not None:
            advance(require_utc(now))
        return out


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

"""Per-symbol 24/7 state machine. No global 'all symbols then jury' pass.

IDLE → ARM_ZLG → LABEL_ZLG → JURY. Send only inside the desk window
when user_mode is demo|live and jury is ACCORD. Shadow always writes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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
from capitalizator.champion.calibrate import ClassStat, class_key, class_stats, refuted, to_meta
from capitalizator.champion.drift import PageHinkley
from capitalizator.champion.exam import exam
from capitalizator.champion.shadow_day import (
    challenger_on,
    challenger_tag,
    persist_day,
    row_day_utc,
)
from capitalizator.desk.bars import TF_MINUTES, BarBuilder
from capitalizator.desk.pictures import needs_new_card, picture_for
from capitalizator.desk.session_name import session_name
from capitalizator.exec.ev_gate import evaluate as ev_evaluate
from capitalizator.exec.failed_break import sweep_wick
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.exec.fvg_mark import fvg_present
from capitalizator.exec.ideas import classify as classify_idea
from capitalizator.exec.ideas import opposite as opposite_side
from capitalizator.exec.ideas import shadow_tag as idea_shadow_tag
from capitalizator.exec.ideas import side_for
from capitalizator.exec.manage import TradeManager
from capitalizator.exec.paper import HALF, PaperEngine, PaperPosition
from capitalizator.exec.shadow import ShadowWriter
from capitalizator.exec.smart_stop import initial_stop, soft_exit
from capitalizator.exec.spot import SpotAdapter
from capitalizator.exec.strategy_bounce import (
    BounceSnapshot,
    BounceStrategy,
    in_mid_range,
    opposing_target,
    price_in_zone,
    stop_behind,
    stop_behind_wick,
    take_profit,
)
from capitalizator.exec.trail import TrailEngine, TrailState
from capitalizator.exec.tvh import NO_TVH, tvh_ok
from capitalizator.instruments import Instrument, InstrumentRegistry, InstrumentUnknown
from capitalizator.jury.desk import (
    decide,
    voices_for_bounce,
    voices_for_breakout,
    voices_for_failed_break,
    voices_for_spring,
)
from capitalizator.memory.journal import JOURNAL_KEYS, empty_journal
from capitalizator.memory.registry import Registry, Touch
from capitalizator.memory.revive import load_pending
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.rules import MacroRules
from capitalizator.news_macro.unlocks import Unlocks
from capitalizator.oko.eye import OkoEye, OkoWindow
from capitalizator.oko.footprint import FINGERPRINT_LEN as OKO_FINGERPRINT_LEN
from capitalizator.oko.forecast import Sample as OkoSample
from capitalizator.oko.forecast import class_key as oko_class_key
from capitalizator.oko.retina import RawWindow
from capitalizator.oko.shadow import FINGERPRINT_LEN as OKO_SHADOW_FP_LEN
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.phase import breakout_enabled
from capitalizator.ops.product import DEFAULT_MODE, META_HELLO
from capitalizator.patterns.bar_quality import atr as atr_of
from capitalizator.patterns.bar_quality import classify_bar_quality
from capitalizator.patterns.cav import label as cav_label
from capitalizator.patterns.cav import prior_compress
from capitalizator.patterns.width import WidthSample, width_now_from_history, width_rank
from capitalizator.prs.score import PRS
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.risk.account import Account
from capitalizator.risk.config import load_risk_config
from capitalizator.risk.drift_cut import target_after_drift
from capitalizator.risk.schema import Intent
from capitalizator.risk.session import (
    SessionWindow,
    cpi_day,
    in_desk_window,
    us_data_known_at,
)
from capitalizator.risk.sizing import size_position
from capitalizator.tape.classify import TapeClassifier
from capitalizator.tape.ofi import OFI
from capitalizator.types import MarketEvent, require_utc
from capitalizator.whales.fragility import forbid_new_long, forbid_new_short
from capitalizator.zlg.gesture import ZLG, BookAdd, BookPull
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import MAP_VOTE_METHODS
from capitalizator.zones.map import ZoneMap
from capitalizator.zones.model import Bar, Zone

State = Literal["IDLE", "ARM_ZLG", "LABEL_ZLG", "JURY"]
_IDEAS = frozenset({"bounce", "spring", "breakout", "failed_break"})
# ОКО Footprint feeds kept per symbol. OI/funding tick every few seconds; a touch
# window needs the last value before the print and the last inside 8s.
_FEED_KEEP = timedelta(hours=2)


@dataclass
class SymbolState:
    symbol: str
    book: Book
    book_pre: Book | None = None
    state: State = "IDLE"
    armed_at: datetime | None = None
    adds: list[BookAdd] = field(default_factory=list)
    pulls: list[BookPull] = field(default_factory=list)
    trades: list[MarketEvent] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    last_touch: Touch | None = None
    book_history: list[tuple[datetime, Book]] = field(default_factory=list)
    bar_builder: BarBuilder | None = None
    bars_seeded: int = 0
    trades_dropped: int = 0
    zlg_card: CardLive | None = None
    oko_window: OkoWindow | None = None
    oi: list[tuple[datetime, Decimal]] = field(default_factory=list)
    funding: list[tuple[datetime, Decimal]] = field(default_factory=list)
    liquidations: list[MarketEvent] = field(default_factory=list)


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
        tick_size: Decimal | None = None,
        calendar: tuple[NewsRow, ...] = (),
        btc: BtcBus | None = None,
        unlocks: Unlocks | None = None,
        instruments: InstrumentRegistry | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.user_mode = user_mode
        # tick_size given explicitly = legacy single-tick mode (fixtures / tests).
        # None = strict: a symbol missing from the instrument registry is refused.
        self.legacy_tick = tick_size
        self.tick_size = tick_size if tick_size is not None else Decimal("0.1")
        self.instruments = instruments if instruments is not None else InstrumentRegistry.offline()
        self.refused_symbols: dict[str, str] = {}
        self.calendar = calendar
        self.btc = btc if btc is not None else BtcBus()
        self.unlocks = unlocks if unlocks is not None else Unlocks.load()
        self.config = load_registry()
        self.symbols: dict[str, SymbolState] = {}
        self.registry = Registry(
            tick_size=self.tick_size, config=self.config, tick_for=self.tick_for
        )
        self.shadow = ShadowWriter()
        self.session = SessionWindow()
        # D-09/D-10/D-13: one Account owns equity, open ideas, halts and the
        # per-session budget; RiskEngine/Halts are its members, not orphans.
        self.risk_config = load_risk_config(knowledge)
        self.account = Account.load(knowledge, self.risk_config)
        self.risk = self.account.risk
        self.halts = self.account.halts
        self.funding: dict[str, Decimal] = {}
        self._funding_hist: dict[str, list[Decimal]] = {}
        self._oi_hist: dict[str, list[tuple[datetime, Decimal]]] = {}
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
        self.zlg = ZLG(tick_size=self.tick_size, config=self.config)
        self.tape = TapeClassifier()
        self.zones_map = ZoneMap(self.config)
        self.first_minute = FirstMinute()
        self.btc_veto = BtcVeto()
        self.btc_regime = BtcRegime(self.zones_map)
        self.manager = TradeManager()
        self.spot = SpotAdapter(knowledge)
        # W3: every shadow / fade / demo idea is executed on paper against the tape.
        self.paper = PaperEngine(
            funding_rate=lambda s: self.funding.get(s),
            on_close=self._on_paper_close,
            max_hold=timedelta(hours=self.config.touch_pending_timeout_h),
        )
        # W4: structure / venue trailing for every open paper position (and, via the
        # gateway, for live positions). One TrailState per paper_id.
        self.trail = TrailEngine(mode=self.risk_config.trail_mode)
        self._trails: dict[str, TrailState] = {}
        self._half_sent: set[str] = set()
        self.entries_paused = False
        self._instruments_seen: str | None = None
        self._calibration: dict[str, ClassStat] = {}
        self._calibration_at: datetime | None = None
        self.drift_active = False
        self.oko = OkoEye(working_tf=self.config.working_tf)
        self.shadow_writes: list[dict[str, Any]] = []
        self.last_price: dict[str, Decimal] = {}
        # Symbols the venue has shown a position or a fill for (venue_flat needs proof
        # the venue ever held the idea before it may close the twin).
        self._venue_seen: set[str] = set()
        self._paper_dirty = False
        if knowledge.available():
            self.oko.load(knowledge)
            # Twins (pending/open paper positions) survive a restart: the position the
            # venue still holds keeps its trail / half / stop logic (audit B3).
            raw_twins = knowledge.meta("paper_open")
            if raw_twins:
                try:
                    restored = self.paper.restore(json.loads(raw_twins))
                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                    knowledge.set_meta("paper_open_error", str(exc))
                else:
                    knowledge.set_meta("paper_restored", str(restored))
            raw_seen = knowledge.meta("venue_seen")
            if raw_seen:
                try:
                    self._venue_seen = set(json.loads(raw_seen))
                except (json.JSONDecodeError, TypeError):
                    self._venue_seen = set()
            for symbol, raw in knowledge.last_prices().items():
                try:
                    px = Decimal(str(raw))
                except ArithmeticError:
                    continue
                if px > 0:
                    self.last_price[symbol] = px
            for key, raw in knowledge.meta_prefix("label_count:").items():
                parts = key.split(":", 3)
                if len(parts) == 4 and raw.isdigit():
                    self.registry.archived[(parts[1], parts[2], parts[3])] = int(raw)
            zones, pending = load_pending(knowledge)
            for zone in zones:
                self.registry._zones[zone.zone_id] = zone
            have = {touch.touch_id for touch in self.registry.touches}
            self.registry.touches.extend(
                touch for touch in pending if touch.touch_id not in have
            )
        self.open_card_id: dict[str, str] = {}
        self.walls: dict[str, WallWatch] = {}
        self.prs: dict[str, PRS] = {}
        self._width_history: list[WidthSample] = []
        self._ui_pending: dict[str, str] = {}
        self._ui_last_flush: datetime | None = None
        self.zone_cache: dict[str, tuple[tuple[Any, ...], tuple[Zone, ...]]] = {}
        self._persisted_zone_ids: dict[str, frozenset[str]] = {}
        self._last_settle: datetime | None = None
        if knowledge.available():
            self._reload_instruments()
            self._load_oi_history()

    def tick_for(self, symbol: str) -> Decimal:
        """Instrument tick. Legacy mode falls back to the constructor tick."""
        if self.instruments.has(symbol):
            return self.instruments.tick(symbol)
        if self.legacy_tick is not None:
            return self.legacy_tick
        raise InstrumentUnknown(symbol)

    def instrument_ok(self, symbol: str) -> bool:
        """False (and remembered for the UI) when no instrument facts exist."""
        try:
            self.tick_for(symbol)
        except InstrumentUnknown:
            self.refused_symbols[symbol] = "instrument_unknown"
            return False
        return True

    def state_for(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(
                symbol=symbol,
                book=Book(tick_size=str(self.tick_for(symbol))),
                bar_builder=BarBuilder(
                    symbol=symbol,
                    tfs=(self.config.working_tf, self.config.htf, self.config.htf_d1),
                ),
            )
        return self.symbols[symbol]

    # --- bounded buffers -------------------------------------------------
    def _trade_keep_window(self) -> timedelta:
        """Prints needed after a touch: the working bar that closes it plus the 8s window."""
        minutes = TF_MINUTES.get(self.config.working_tf, 15)
        return timedelta(minutes=minutes + 5, seconds=2 * self.config.zlg_window_s)

    def _trim_trades(self, st: SymbolState, now: datetime) -> None:
        keep_from = now - self._trade_keep_window()
        if st.last_touch is not None and st.state != "IDLE":
            keep_from = min(keep_from, st.last_touch.ts - timedelta(seconds=1))
        drop = 0
        for trade in st.trades:
            if trade.exchange_ts >= keep_from:
                break
            drop += 1
        if drop:
            del st.trades[:drop]
            st.trades_dropped += drop

    # --- batched UI meta writes -------------------------------------------
    UI_FLUSH_S = 0.5
    ARCHIVE_AFTER = timedelta(hours=24)

    def _ui_put(self, key: str, value: str) -> None:
        self._ui_pending[key] = value

    def _ui_due(self, now: datetime) -> bool:
        return (
            self._ui_last_flush is None
            or (now - self._ui_last_flush).total_seconds() >= self.UI_FLUSH_S
        )

    def flush_ui(self, now: datetime, *, force: bool = False) -> int:
        """Write last_price / book snapshots in one transaction, at most every 0.5s."""
        if not self._ui_pending or not self.knowledge.available():
            return 0
        if (
            not force
            and self._ui_last_flush is not None
            and (now - self._ui_last_flush).total_seconds() < self.UI_FLUSH_S
        ):
            return 0
        n = len(self._ui_pending)
        self.knowledge.set_meta_many(self._ui_pending)
        self._ui_pending = {}
        self._ui_last_flush = now
        return n

    def hello_ok(self) -> bool:
        return self.knowledge.meta(META_HELLO) == "1"

    def contour_on(self) -> bool:
        raw = self.knowledge.meta("contour")
        return raw == "on"

    def persist_zones(self, zones: Sequence[Zone]) -> None:
        if not self.knowledge.available() or not zones:
            return
        # Same map as last time for these symbols → nothing to write (was one
        # full `zone` table read + one transaction per print).
        by_symbol: dict[str, set[str]] = {}
        for z in zones:
            by_symbol.setdefault(z.symbol, set()).add(z.zone_id)
        if all(
            self._persisted_zone_ids.get(sym) == frozenset(ids)
            for sym, ids in by_symbol.items()
        ):
            return
        for sym, ids in by_symbol.items():
            self._persisted_zone_ids[sym] = frozenset(ids)
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
        if self.knowledge.available() and self._ui_due(when):
            # Build the UI book JSON only when a flush is due (was: sort + dumps per diff).
            bids = sorted(
                ((str(px), str(sz)) for px, sz in st.book.levels("bid").items()),
                reverse=True,
            )[:20]
            asks = sorted((str(px), str(sz)) for px, sz in st.book.levels("ask").items())[:20]
            self._ui_put(
                f"book:{st.symbol}",
                json.dumps(
                    {"symbol": st.symbol, "bids": bids, "asks": asks, "ts": when.isoformat()},
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            )
            self.flush_ui(when)

    # A "wall" is a notional, not a coin count: 50 BTC ≈ $3M at 60k. The same
    # threshold in coins made every DOGE level a wall and no SOL level one.
    WALL_MIN_NOTIONAL = Decimal("3000000")

    def _wall_for(self, symbol: str) -> WallWatch:
        px = self.last_price.get(symbol)
        if symbol not in self.walls:
            size = self.WALL_MIN_NOTIONAL / px if px else Decimal("50")
            self.walls[symbol] = WallWatch(symbol, min_size=size)
        elif px:
            # follow the price: the wall stays a $3M object as the coin moves
            self.walls[symbol].min_size = self.WALL_MIN_NOTIONAL / px
        return self.walls[symbol]

    def _prs_for(self, symbol: str) -> PRS:
        if symbol not in self.prs:
            self.prs[symbol] = PRS(tick_size=self.tick_for(symbol), config=self.config)
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
                st.book = Book(tick_size=str(self.tick_for(st.symbol)))
                return
            # Only the touched prices can change: read them before the diff instead of
            # copying the whole book (was 0.9 ms per diff in the profile).
            before: dict[tuple[str, Decimal], Decimal] = {}
            if st.book.ready:
                for side_name, rows in (("bid", bids), ("ask", asks)):
                    levels = st.book.levels(side_name)  # type: ignore[arg-type]
                    for px_s, _sz in rows:
                        px = Decimal(px_s)
                        before[(side_name, px)] = levels.get(px, Decimal("0"))
            try:
                st.book.apply_diff(bids, asks, seq=int(seq))
            except (BookDirty, SeqFault):
                st.book = Book(tick_size=str(self.tick_for(st.symbol)))
                return
            _record_adds_from_diff(st, event.exchange_ts, before, bids, asks)
            if st.state == "IDLE" and (len(st.adds) > 256 or len(st.pulls) > 256):
                # Adds/pulls only matter inside the 8s window after a touch; idle
                # symbols must not accumulate hours of book activity.
                keep_from = event.exchange_ts - timedelta(seconds=2 * self.config.zlg_window_s)
                st.adds = [a for a in st.adds if a.ts >= keep_from]
                st.pulls = [a for a in st.pulls if a.ts >= keep_from]
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
                    st.pulls.clear()
                    st.trades.clear()
                    st.book_pre = None
                    st.oko_window = None
                action = self.manager.on_refute(load_bearing=True, verdict="REFUTED")
                flattened = 0
                when = event.get("now")
                when = require_utc(when) if isinstance(when, datetime) else datetime.now(tz=UTC)
                if symbol and symbol in self.last_price:
                    flattened = len(
                        self.paper.flatten(symbol, self.last_price[symbol], when, reason="flatten")
                    )
                if symbol and self.knowledge.available() and self.user_mode in {"demo", "live"}:
                    self.knowledge.enqueue_oms(
                        kind="flatten", symbol=symbol,
                        payload={"reason": str(event.get("reason") or "operator")},
                        created_ts=when.isoformat(),
                    )
                return [
                    {
                        "event": "flatten",
                        "symbol": symbol,
                        "state": "IDLE",
                        "action": None if action is None else action.action,
                        "paper_flattened": flattened,
                    }
                ]
            if kind == "bar_close":
                bar = event.get("bar")
                if not isinstance(bar, Bar):
                    raise ValueError("bar_close needs a Bar")
                if not self.instrument_ok(bar.symbol):
                    return [_refused(bar.symbol)]
                return self.on_bar_close(bar)
            raise ValueError(f"unknown desk event: {kind!r}")
        if not self.instrument_ok(event.symbol):
            return [_refused(event.symbol)]
        if event.stream == "trades":
            return self.on_trade(event, zones or [])
        st = self.state_for(event.symbol)
        if event.stream in {"book_diff", "bbo", "snapshot"}:
            self._apply_book_event(st, event)
            return [{"event": event.stream, "symbol": event.symbol}]
        if event.stream in {"funding", "oi", "mark"}:
            # Recorder emits these. Funding feeds the EV gate (expected hold cost).
            # OI / funding / liquidations are kept per symbol for the ОКО Footprint
            # (INVENTION-OKO §След). No journal row is written here.
            if event.stream == "funding":
                try:
                    self.funding[event.symbol] = Decimal(str(event.payload["funding"]))
                except (KeyError, ArithmeticError):
                    pass
            self._keep_feed(st, event)
            return [{"event": event.stream, "symbol": event.symbol}]
        if event.stream == "liquidation":
            self._keep_feed(st, event)
            return [{"event": event.stream, "symbol": event.symbol}]
        if event.stream in {"gap", "resync"}:
            if event.stream == "resync" and event.payload.get("bids") and event.seq is not None:
                # The recorder resynced from REST and shipped the levels: rebuild, do not wipe.
                st.book = Book(tick_size=str(self.tick_for(st.symbol)))
                self._apply_book_event(
                    st,
                    MarketEvent(
                        stream="snapshot",
                        exchange=event.exchange,
                        symbol=event.symbol,
                        exchange_ts=event.exchange_ts,
                        recv_ts=event.recv_ts,
                        seq=event.seq,
                        payload={"bids": event.payload["bids"], "asks": event.payload["asks"]},
                    ),
                )
                return [{"event": "resync", "symbol": event.symbol, "book_dirty": False}]
            st.book = Book(tick_size=str(self.tick_for(st.symbol)))
            return [{"event": event.stream, "symbol": event.symbol, "book_dirty": True}]
        raise ValueError(f"unknown stream: {event.stream!r}")

    def on_bar_close(self, bar: Bar) -> list[dict[str, Any]]:
        st = self.state_for(bar.symbol)
        st.bars.append(bar)
        if st.bar_builder is not None:
            st.bar_builder.seed_closed((bar,))
        self.flush_ui(bar.close_ts, force=True)
        if bar.tf == self.config.working_tf:
            # Weather reads only closed working bars. Persist per symbol.
            self.oko.on_bar_close(bar)
            self.oko.save(self.knowledge, symbols=(bar.symbol,))
        if bar.symbol == "BTCUSDT":
            self.btc.bars.append(bar)
            self._publish_btc_bus(st, bar)
        if bar.tf in {self.config.htf, self.config.htf_d1}:
            self.publish_card(bar.symbol, bar.close_ts)
        elif bar.tf == self.config.working_tf and self.calendar:
            # D-21: TTL is 60s, so publishing only on 4h/1d closes left the card
            # stale 239 minutes out of 240. A working close refreshes a stale card
            # (a fresh one — e.g. just written by contour B — is kept).
            self._card_for(bar.symbol, bar.close_ts)
        trail_events: list[dict[str, Any]] = []
        if bar.tf == self.config.working_tf:
            trail_events = self._trail_on_bar(st, bar)
        if st.last_touch is None:
            return trail_events
        if bar.tf != self.config.working_tf:
            return []
        # Plan: LABEL_ZLG (8s) then CAV on a closed bar, then JURY.
        # A working bar can close inside the 8s window — wait for the tick.
        if st.state != "LABEL_ZLG":
            return trail_events
        return self._eval_cav_and_jury(st, bar) + trail_events

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
        if st.bar_builder is not None:
            st.bar_builder.on_trade(trade)
        self._trim_trades(st, trade.exchange_ts)
        for pos in self.paper.on_print(trade):
            # The +1R half on a demo/live twin is a venue order (reduce-only limit).
            if (
                pos.source == "demo"
                and pos.state == "open"
                and pos.half_taken
                and pos.paper_id not in self._half_sent
                and not pos.labels.get("half_sent")
            ):
                self._half_sent.add(pos.paper_id)
                pos.labels["half_sent"] = True  # persisted with the twin: no re-send after restart
                # Half of what the venue actually holds, not of the paper size.
                venue_qty = self._venue_qty(pos.symbol)
                base = venue_qty if venue_qty is not None and venue_qty > 0 else pos.qty
                self._oms(
                    pos, "half_tp", trade.exchange_ts,
                    qty=str(base * HALF), price=str(pos.half_px), reason="+1R half",
                )
        try:
            px = Decimal(str(trade.payload["px"]))
            if px > 0:
                self.last_price[trade.symbol] = px
                if self.knowledge.available():
                    self._ui_put(f"last_price:{trade.symbol}", str(px))
                    self.flush_ui(trade.exchange_ts)
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

    def tick(self, now: datetime, *, force_flush: bool = True) -> list[dict[str, Any]]:
        when = require_utc(now)
        self.account.roll(when)
        self.paper.on_clock(when)
        out: list[dict[str, Any]] = []
        if self.knowledge.available():
            # Gateway watchdog reads this: a silent desk cancels entry orders (§7 / Н-4).
            self._ui_put("desk_heartbeat", when.isoformat())
            if self.refused_symbols:
                self._ui_put("refused_symbols", json.dumps(self.refused_symbols, sort_keys=True))
            if force_flush:
                out.extend(self._consume_commands(when))
                self._reload_risk_config()
                self._reload_instruments()
                self._refresh_calibration(when)
                out.extend(self._sync_exchange_state(when))
            # Twins and venue proof survive a restart (audit B3).
            self._ui_put("paper_open", json.dumps(self.paper.snapshot(), sort_keys=True))
            self._ui_put("venue_seen", json.dumps(sorted(self._venue_seen)))
        self.flush_ui(when, force=force_flush)
        # Settling pending touches walks every touch; once per second of clock is
        # enough (outcomes are 15m closes / 8-tick moves / 6h timeouts).
        if (
            force_flush
            or self._last_settle is None
            or (when - self._last_settle).total_seconds() >= 1.0
        ):
            out.extend(self._settle_shadows(when))
            self._last_settle = when
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
            learned = False
            for touch in changed:
                events.append(
                    {
                        "event": "shadow_outcome",
                        "touch_id": touch.touch_id,
                        "outcome": touch.outcome,
                    }
                )
                learned = self._oko_learn(symbol, touch) or learned
                row = self.knowledge.get_journal_touch(touch.touch_id)
                if row is None:
                    continue
                row["outcome"] = touch.outcome
                day = row_day_utc(row)
                if day:
                    days.add(day)
                self.knowledge.put_journal_touch(touch.touch_id, row)
            if learned:
                self.oko.save(self.knowledge, symbols=(symbol,))
        for day in days:
            persist_day(self.knowledge, day)
        # Resolved touches older than a day leave memory; their label counts stay.
        gone = self.registry.archive_resolved(now=now, max_age=self.ARCHIVE_AFTER)
        if gone and self.knowledge.available():
            for (kind, label, symbol), n in self.registry.archived.items():
                self._ui_put(f"label_count:{kind}:{label}:{symbol}", str(n))
            self.flush_ui(now, force=True)
        return events

    def _keep_feed(self, st: SymbolState, event: MarketEvent) -> None:
        """OI / funding / liquidation rows for the Footprint. Bad numbers are dropped."""
        when = require_utc(event.exchange_ts)
        keep_from = when - _FEED_KEEP
        if event.stream == "oi":
            try:
                level = Decimal(str(event.payload["oi"]))
            except (KeyError, ArithmeticError):
                return
            if level <= 0:
                return
            st.oi.append((when, level))
            st.oi = [row for row in st.oi if row[0] >= keep_from]
            self._sample_oi_history(st.symbol, when, level)
        elif event.stream == "funding":
            try:
                rate = Decimal(str(event.payload["funding"]))
            except (KeyError, ArithmeticError):
                return
            st.funding.append((when, rate))
            st.funding = [row for row in st.funding if row[0] >= keep_from]
        elif event.stream == "liquidation":
            if event.payload.get("position") not in {"long", "short"}:
                return
            try:
                if Decimal(str(event.payload["qty"])) <= 0:
                    return
            except (KeyError, ArithmeticError):
                return
            st.liquidations.append(event)
            st.liquidations = [
                row for row in st.liquidations if require_utc(row.exchange_ts) >= keep_from
            ]

    def _oko_learn(self, symbol: str, touch: Touch) -> bool:
        """Immune memory: fingerprint × idea × outcome. die teaches nothing."""
        if touch.outcome == "pending" or not touch.oko_fingerprint or not touch.idea:
            return False
        try:
            fingerprint = tuple(int(v) for v in touch.oko_fingerprint.split("-"))
        except ValueError:
            return False
        if len(fingerprint) == OKO_SHADOW_FP_LEN:
            # Rows stamped before the Footprint organ carry 10 ints: the Footprint
            # axes are padded with the neutral bucket, the same way the memory
            # migrates its persisted antigens.
            fingerprint = fingerprint + (0,) * (OKO_FINGERPRINT_LEN - OKO_SHADOW_FP_LEN)
        if len(fingerprint) != OKO_FINGERPRINT_LEN:
            return False
        # Antigen carries the touch time, not the tick that resolved it: replay-stable.
        return self.oko.learn(
            symbol=symbol,
            fingerprint=fingerprint,
            idea=touch.idea,
            outcome=touch.outcome,
            ts=touch.ts,
        )

    def _oko_raw_window(self, st: SymbolState, touch: Touch) -> RawWindow | None:
        """Frozen 8s window for ОКО. None when the book at the print was not ready."""
        pre = st.book_pre
        if pre is None or not pre.ready:
            return None
        zone = self.registry.zone(touch.zone_id)
        window_s = self.config.zlg_window_s
        t_end = touch.ts + timedelta(seconds=window_s)
        path = tuple(
            (ts, copy)
            for ts, copy in st.book_history
            if copy.ready and touch.ts <= ts <= t_end
        )
        since = touch.ts - timedelta(seconds=window_s)
        walls = self.walls[st.symbol].events if st.symbol in self.walls else []
        return RawWindow(
            symbol=st.symbol,
            zone=zone,
            t0=touch.ts,
            window_s=window_s,
            tick_size=self.tick_for(st.symbol),
            delta_ticks=self.config.prs_delta_ticks,
            book_pre=pre,
            book_path=path,
            trades=tuple(
                t
                for t in st.trades
                if t.stream == "trades" and touch.ts <= require_utc(t.exchange_ts) <= t_end
            ),
            adds=tuple(a for a in st.adds if touch.ts <= a.ts <= t_end),
            wall_events=tuple(e for e in walls if since <= e.ts <= t_end),
            oi_path=tuple(sorted((ts, lv) for ts, lv in st.oi if ts <= t_end)),
            liquidations=tuple(
                row for row in st.liquidations if touch.ts <= require_utc(row.exchange_ts) <= t_end
            ),
            funding=next((rate for ts, rate in reversed(st.funding) if ts <= t_end), None),
        )

    def _oko_samples(self) -> list[OkoSample]:
        """Resolved touches as Forecast samples. Journal first, then unsaved rows."""
        out: list[OkoSample] = []
        seen: set[str] = set()
        for row in self.knowledge.journal_rows():
            touch_id = str(row.get("touch_id") or "")
            outcome = row.get("outcome")
            idea = row.get("idea")
            symbol = row.get("symbol")
            if not touch_id or idea not in _IDEAS or not symbol:
                continue
            if outcome not in {"bounce", "break", "die"}:
                continue
            seen.add(touch_id)
            out.append(
                OkoSample(
                    symbol=str(symbol),
                    # The same six axes `judge` uses — footprint included. A key built
                    # without it never matched the judge's key and n_class stayed 0
                    # forever (audit B7).
                    class_key=oko_class_key(
                        idea=str(idea),
                        cav=row.get("cav_label"),
                        zlg=row.get("zlg_label"),
                        regime=row.get("oko_regime"),
                        footprint=row.get("oko_footprint"),
                    ),
                    outcome=str(outcome),
                )
            )
        for touch in self.registry.touches:
            if touch.touch_id in seen or touch.outcome == "pending" or touch.idea not in _IDEAS:
                continue
            zone = self.registry._zones.get(touch.zone_id)
            if zone is None:
                continue
            out.append(
                OkoSample(
                    symbol=zone.symbol,
                    class_key=oko_class_key(
                        idea=touch.idea,
                        cav=touch.cav_label,
                        zlg=touch.gesture,
                        regime=touch.oko_regime,
                        footprint=touch.oko_footprint,
                    ),
                    outcome=touch.outcome,
                )
            )
        return out

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
        # D-18: contour B never stops labelling. ZLG / tape / PRS / CAV are stamped
        # on every touch (the 24/7 shadow learns from all of them); the B verdict
        # only decides skip_reason / shadow_would / send in _eval_cav_and_jury.
        # The card read on the 8s clock is remembered: if none is fresh at the bar
        # close, the verdict that was current when the touch armed still applies.
        st.zlg_card = self._card_for(st.symbol, now)
        # ОКО reads the frozen window on the same 8s clock (Retina + Shadow + Footprint).
        # A B verdict is a fact about the calendar, not about the book: the Passport
        # learns every window and the journal carries the facts either way.
        self._oko_observe(st, touch, now)
        touch = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
        st.last_touch = touch
        book = st.book_pre or st.book
        bid, ask = book.best() if book.ready else (None, None)
        mid = ((bid + ask) / 2) if bid is not None and ask is not None else touch.trade_px
        hit_side = "bid" if zone.side == "support" else "ask"
        opp_best = ask if hit_side == "bid" else bid
        if opp_best is None:
            opp_best = touch.trade_px
        t_end = touch.ts + timedelta(seconds=self.config.zlg_window_s)
        prints = [
            (require_utc(t.exchange_ts), Decimal(str(t.payload["px"])))
            for t in st.trades
            if t.stream == "trades" and "px" in t.payload
            and touch.ts <= require_utc(t.exchange_ts) <= t_end
        ]
        result = self.zlg.classify(
            touch,
            st.adds,
            touch.trade_qty,
            hit_side=hit_side,
            mid=mid,
            opp_best=opp_best,
            book_ready=book.ready,
            tick=self.tick_for(st.symbol),
            book_pulls=st.pulls,
            prints=prints,
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

    def _oko_observe(self, st: SymbolState, touch: Touch, now: datetime) -> None:
        """Retina + Shadow on the frozen 8s window. Same clock as ZLG / OFI / PRS."""
        st.oko_window = None
        raw = self._oko_raw_window(st, touch)
        if raw is None:
            return
        window = self.oko.observe_window(raw, touch_id=touch.touch_id, now=now)
        st.oko_window = window
        self.registry.fill_oko_window(
            label=window.shadow.label,
            fingerprint=window.fingerprint_text,
            book_trust=_f(window.shadow.book_trust),
            tape_trust=_f(window.shadow.tape_trust),
            footprint=window.footprint.label,
            footprint_side=window.footprint.side,
            touch_id=touch.touch_id,
        )
        self.oko.save(self.knowledge, symbols=(st.symbol,))

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

    @staticmethod
    def _b_gate_kind(card: CardLive | None, *, zone_side: str = "support") -> str | None:
        """B verdict as a skip reason: b_veto | b_hold | b_marks | None (allowed).

        Marks are read for the touch's side (fib retrace from the high for a long,
        from the low for a short — D-20). Never stops labelling.
        """
        if card is None:
            return None
        if card.bearing_verdict == "veto":
            return "b_veto"
        if card.bearing_verdict == "hold":
            return "b_hold"
        if card.bearing_verdict in {"propose", "cut_size"} and not card.context_ok(
            side="buy" if zone_side == "support" else "sell"
        ):
            return "b_marks"
        return None

    def _eval_cav_and_jury(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        touch = st.last_touch
        if touch is None:
            return []
        zone = self.registry.zone(touch.zone_id)
        card = self._card_for(st.symbol, bar.close_ts)
        if card is None and st.zlg_card is not None:
            card = st.zlg_card
        b_gate = self._b_gate_kind(card, zone_side=zone.side)
        marks_red = b_gate == "b_marks"
        if marks_red and not self.risk_config.require_ict_marks:
            # D-19: red ICT marks are recorded, not enforced (operator knob).
            b_gate = None
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
        compress_before = prior_compress(
            zone, bar, t=closed_at, htf_bias=htf, closed_bars=st.bars
        )
        known_zones = tuple(
            z for z in self.registry._zones.values() if z.symbol == st.symbol
        ) or (zone,)
        if in_mid_range(
            bar.close,
            known_zones,
            tick=self.tick_for(st.symbol),
            band_ticks=self.config.mid_band_ticks,
        ):
            cav = "NOISE"
        self.registry.fill_cav(cav_label=cav, touch_id=touch.touch_id)
        live = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
        # exec/ideas: THROUGH → breakout; wick through + close inside → spring
        # (the held level, traded WITH the zone); else bounce. No side inversion.
        idea = classify_idea(zone=zone, bar=bar, cav_label=live.cav_label)
        wick_extreme = bar.low if zone.side == "support" else bar.high
        if live.btc_regime is None and self.btc.regime:
            # Published bus only. Alt H4 is not BTC; BTC already wrote the bus
            # on this close (on_bar_close publishes before jury).
            self.registry.fill_btc(regime=self.btc.regime, touch_id=touch.touch_id)
        n_cav = self.registry.count_label("cav", live.cav_label, st.symbol)
        n_zlg = self.registry.count_label("zlg", live.gesture, st.symbol)
        idea_side = side_for(idea, zone.side)
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
        # ОКО judges after CAV/ZLG are facts and before the jury is stamped.
        oko = self.oko.judge(
            idea=idea,
            zone_side=zone.side,
            window=st.oko_window,
            cav=live.cav_label,
            zlg=live.gesture,
            samples=self._oko_samples(),
            symbol=st.symbol,
        )
        self.registry.fill_oko(
            voice=oko.voice,
            label=oko.label,
            regime=oko.regime,
            reason=oko.reason,
            book_trust=_f(oko.book_trust),
            tape_trust=_f(oko.tape_trust),
            cp_prob=_f(oko.cp_prob),
            p_bounce=_f(oko.p_bounce) or "0",
            p_break=_f(oko.p_break) or "0",
            p_die=_f(oko.p_die) or "0",
            pred_set=oko.set_text,
            n_class=oko.n_class,
            size_mult=str(oko.size_mult),
            fingerprint="-".join(str(v) for v in oko.fingerprint),
            footprint=oko.footprint,
            footprint_side=oko.footprint_side,
            oi_z=_f(oko.oi_z),
            liq_rel=_f(oko.liq_rel),
            touch_id=touch.touch_id,
        )
        self.oko.save(self.knowledge, symbols=(st.symbol,))
        live = next(t for t in self.registry.touches if t.touch_id == touch.touch_id)
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
            oko_voice=oko.voice,
        )
        row = stamped[0] if stamped else live
        first = resolve_first_fact(row.gesture, n_zlg)
        self._stamp_journal_atoms(st, bar, zone, row, closed_at)
        row = next(t for t in self.registry.touches if t.touch_id == row.touch_id)
        voice_fn = {
            "bounce": voices_for_bounce,
            "spring": voices_for_spring,
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
            oko=oko.voice,
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
            tick=self.tick_for(st.symbol),
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
        # Challenger readings so data, not a comment, decides whether ICT marks help:
        #   shadow_would_no_marks — ACCORD ∧ TVH regardless of marks
        #   shadow_would_marks    — the same, only when the marks are green
        shadow_would_no_marks = shadow_would and has_tvh and b_gate in {None, "b_marks"}
        shadow_would_marks = shadow_would_no_marks and not marks_red
        skip: str | None
        if not has_tvh:
            shadow_would = False
            skip = NO_TVH
        elif shadow_would:
            skip = None
        else:
            skip = first.tag if first.tag == "shadow_gesture" else jury
        if b_gate is not None:
            # B is part of the strategy: the shadow respects veto / hold / marks and
            # the operator sees the B reason first (TVH is journalled separately).
            shadow_would = False
            skip = b_gate
        if idea == "breakout" and not breakout_enabled() and skip is None:
            skip = "breakout_off"
        shadow_side = idea_side if shadow_would else None
        shadow_tag = idea_shadow_tag(idea) if shadow_would else None
        # Challenger reading of the same spring bar: the old short against it.
        # Shadow-only; the paper engine scores both so data, not a comment, decides.
        fade_side = opposite_side(idea_side) if idea == "spring" else None
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
        # A fast touch can resolve before its jury bar closes. _settle_shadows learns
        # only rows that already carry `idea` (stamped just above), so this is the
        # single place such a row is learned — never twice.
        if row.outcome != "pending" and self._oko_learn(st.symbol, row):
            self.oko.save(self.knowledge, symbols=(st.symbol,))
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
                "oko_voice": row.oko_voice,
                "oko_label": row.oko_label,
                "oko_regime": row.oko_regime,
                "oko_reason": row.oko_reason,
                "oko_book_trust": row.oko_book_trust,
                "oko_tape_trust": row.oko_tape_trust,
                "oko_cp_prob": row.oko_cp_prob,
                "oko_p_bounce": row.oko_p_bounce,
                "oko_p_break": row.oko_p_break,
                "oko_p_die": row.oko_p_die,
                "oko_set": row.oko_set,
                "oko_n_class": row.oko_n_class,
                "oko_size_mult": row.oko_size_mult,
                "oko_fingerprint": row.oko_fingerprint or None,
                "oko_footprint": row.oko_footprint,
                "oko_footprint_side": row.oko_footprint_side,
                "oko_oi_z": row.oko_oi_z,
                "oko_liq_rel": row.oko_liq_rel,
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
                        tick_size=self.tick_for(st.symbol),
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
            "had_compress": compress_before,
            "zone_side": zone.side,
            "idea_side": idea_side,
            "wick_extreme": str(wick_extreme),
            "fade_side": fade_side,
            "fade_tag": "fade_spring" if fade_side else None,
            "b_gate": b_gate,
            "b_marks_red": marks_red,
            "has_tvh": has_tvh,
            "shadow_would_no_marks": shadow_would_no_marks,
            "shadow_would_marks": shadow_would_marks,
        }
        payload_row = {**journal, **extra}
        payload_row["challenger_would"] = challenger_on(payload_row)
        payload_row["challenger_tag"] = challenger_tag(payload_row)
        b_action = None
        if b_gate == "b_veto":
            # 3.14.3 law kept: a veto on a load-bearing claim flattens an open idea —
            # the demo/live twin on paper AND the venue position via the OMS queue.
            act = self.manager.on_refute(load_bearing=True, verdict="veto")
            b_action = None if act is None else act.action
            twins = self.paper.open_for(st.symbol, source="demo")
            if twins:
                px = self.last_price.get(st.symbol, row.trade_px)
                for twin in twins:
                    self._oms(twin, "flatten", closed_at, reason="b_veto")
                self.paper.flatten(st.symbol, px, closed_at, reason="b_veto")
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
        if len(self.shadow_writes) > self.SHADOW_WRITES_MAX:
            del self.shadow_writes[: len(self.shadow_writes) - self.SHADOW_WRITES_MAX]
        # W3: shadow and fade ideas trade on paper 24/7, whatever the user mode.
        paper_ids: dict[str, str] = {}
        if shadow_would:
            pid = self._submit_paper(
                row, zone, known_zones, idea=idea, side=idea_side, wick_extreme=wick_extreme,
                now=closed_at, source="shadow", tag=idea_shadow_tag(idea),
            )
            if pid:
                paper_ids["shadow"] = pid
        if fade_side is not None and has_tvh:
            pid = self._submit_paper(
                row, zone, known_zones, idea="fade_spring", side=fade_side,
                wick_extreme=wick_extreme, now=closed_at, source="fade", tag="fade_spring",
            )
            if pid:
                paper_ids["fade"] = pid
        if paper_ids:
            payload_row["paper_ids"] = paper_ids
            self.knowledge.put_journal_touch(row.touch_id, payload_row)
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
                fragility = self._fragility(st)
                payload_row["fragility"] = fragility
                snap = BounceSnapshot(
                    now=closed_at,
                    symbol=st.symbol,
                    price=row.trade_px,
                    tick=self.tick_for(st.symbol),
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
                    # instruments-info status: anything but Trading is not a market we enter
                    delisted=not self._instrument_for(st.symbol).trading,
                    funding_extreme=self._funding_extreme(st.symbol),
                    idea=idea,
                    wick_extreme=wick_extreme,
                    atr=self._atr_for(st),
                    spread_abs=spr,
                    stop_mode=self.risk_config.stop_mode,
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
                    b_marks_ok=(
                        True
                        if card is None or not self.risk_config.require_ict_marks
                        else card.context_ok(side=idea_side)
                    ),
                    rvol=(
                        None
                        if card is None or not card.volume.rvol
                        else Decimal(card.volume.rvol)
                    ),
                    wall_state=None if card is None else card.volume.walls,
                    venue="perp" if card is None else card.venue,
                    spot_acked=False if card is None else self.spot.acked(st.symbol),
                    oko_voice=oko.voice,
                    oko_size_mult=oko.size_mult,
                    fragile_long=bool(fragility["forbid_long"]),
                    fragile_short=bool(fragility["forbid_short"]),
                )
                self.strategy.budget = self.account.budget(closed_at)
                intent = self.strategy.propose(snap)
                if intent is not None:
                    sized, gate_info = self._size_and_gate(
                        intent, st.symbol, closed_at,
                        labels={"cav_label": row.cav_label, "zlg_label": row.gesture},
                    )
                    payload_row.update(gate_info)
                    self.knowledge.put_journal_touch(row.touch_id, payload_row)
                    if sized is not None:
                        intent_id = self.knowledge.enqueue_intent(
                            sized.model_dump(mode="json"),
                            created_ts=row.ts.isoformat(),
                        )
                        # Budget is spent here, on an intent that passed every gate.
                        self.account.budget(closed_at).on_intent()
                        self.account.on_open(sized, now=closed_at, intent_id=intent_id)
                        # Demo accounting runs on paper until exchange fills replace it.
                        demo_pid = f"{row.touch_id}:demo"
                        assert sized.qty is not None
                        self.paper.submit(
                            paper_id=demo_pid,
                            touch_id=row.touch_id,
                            symbol=st.symbol,
                            side=sized.side,
                            limit_px=sized.entry,
                            qty=sized.qty,
                            stop=sized.stop,
                            tp=sized.tp,
                            tick=self.tick_for(st.symbol),
                            now=closed_at,
                            valid_for=timedelta(
                                minutes=TF_MINUTES.get(self.config.working_tf, 15)
                                * self.INTENT_TTL_BARS
                            ),
                            source="demo",
                            tag=sized.tag,
                            funding_interval_min=self._instrument_for(st.symbol).funding_interval_min,
                            labels={"cav_label": row.cav_label, "zlg_label": row.gesture,
                                    "symbol": st.symbol, "zone_side": zone.side},
                        )
                        payload_row.setdefault("paper_ids", {})["demo"] = demo_pid
                        payload_row["intent_id"] = intent_id
                        self.knowledge.put_journal_touch(row.touch_id, payload_row)
                        sent = True
        st.state = "IDLE"
        st.last_touch = None
        st.zlg_card = None
        out_event: dict[str, Any] = {
            "event": "jury",
            "touch_id": row.touch_id,
            "jury": jury,
            "sent": sent,
            "skip_reason": skip,
            "touch_line": line,
        }
        if b_action is not None:
            out_event["action"] = b_action
        return [out_event]

    # --- operator commands / config hot reload (D-37, D-12) -------------------------
    DESK_COMMANDS = ("flatten", "release_halts", "pause_entries", "resume_entries", "promote")
    # Bounded in-memory tails for a 24/7 process (audit §5): the journal in SQLite is
    # the record; these are working windows.
    SHADOW_WRITES_MAX = 2000
    WIDTH_HISTORY_MAX = 5000

    def _consume_commands(self, now: datetime) -> list[dict[str, Any]]:
        """Operator commands are claimed atomically (no read-modify-write on meta):
        a command posted between two desk ticks can no longer be lost."""
        out: list[dict[str, Any]] = []
        for cmd in self.knowledge.claim_commands(self.DESK_COMMANDS):
            kind = cmd["kind"]
            payload = cmd["payload"]
            symbol = payload.get("symbol")
            try:
                if kind == "flatten":
                    # ALL = every symbol with a twin or an open idea, not just the ones
                    # this process happened to see a print for.
                    known = (
                        set(self.symbols) | set(self.account.open) | set(self.paper.open_symbols())
                    )
                    targets = sorted(known) if symbol in {None, "ALL"} else [str(symbol)]
                    events: list[dict[str, Any]] = []
                    for sym in targets:
                        events.extend(
                            self.on_event(
                                {
                                    "kind": "flatten",
                                    "symbol": sym,
                                    "now": now,
                                    "reason": payload.get("reason"),
                                }
                            )
                        )
                    out.extend(events)
                    result: dict[str, Any] = {"targets": targets, "events": len(events)}
                elif kind == "release_halts":
                    assert self.account.halts is not None
                    self.account.halts.release(ack=True)
                    self.account.persist()
                    out.append({"event": "release_halts"})
                    result = {"released": True}
                elif kind == "pause_entries":
                    self.entries_paused = True
                    out.append({"event": "pause_entries"})
                    result = {"paused": True}
                elif kind == "resume_entries":
                    self.entries_paused = False
                    out.append({"event": "resume_entries"})
                    result = {"paused": False}
                else:  # promote — run the exam now; flip the label only on a pass
                    result = self._promote(payload, now)
                    out.append({"event": "promote", **{k: result[k] for k in ("passed",)}})
                self.knowledge.mark_command(cmd["id"], "done", result)
            except Exception as exc:  # one bad command must not stop the others
                self.knowledge.mark_command(cmd["id"], "failed", {"error": str(exc)})
                out.append({"event": "command_failed", "kind": kind, "error": str(exc)})
        return out

    def _promote(self, payload: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """Operator asked for the exam. Champion ← challenger only when it passes; the
        report is recorded either way (meta `exam_last`, `champion`)."""
        rows = self.knowledge.paper_trades(limit=100_000)
        report = exam(rows, now=now)
        body = report.to_payload()
        body["requested_by"] = payload.get("reason") or "operator"
        self.knowledge.set_meta("exam_last", json.dumps(body, sort_keys=True))
        if report.passed:
            champion = {
                "since": now.isoformat(),
                "from": "shadow",
                "to": "challenger",
                "report": body,
            }
            self.knowledge.set_meta("champion", json.dumps(champion, sort_keys=True))
        return body

    # --- exchange truth → account (live/demo) --------------------------------------
    EXCHANGE_STATE_MAX_AGE_S = 300.0
    VENUE_FLAT_GRACE_S = 90.0

    def _sync_exchange_state(self, now: datetime) -> list[dict[str, Any]]:
        """In demo/live the signer publishes wallet equity and venue positions (REST truth).

        * equity → Account.set_equity (sizing and halts run on real equity, not paper);
        * an intent the venue refused (`failed`) frees its open idea at once;
        * a filled twin whose venue position is gone (stop/TP/liquidation on the venue)
          is closed here so the account, the one-position rule and the journal agree.
        Shadow/fade twins are untouched: they never went to the venue.
        """
        if self.user_mode not in {"demo", "live"}:
            return []
        out: list[dict[str, Any]] = []
        # 1) intents the venue refused (or the signer could not send at all) free the
        #    idea. `unknown` (transport failed after the order left) and `no_gateway`
        #    (no key yet) keep it: the venue may hold the order / the row is re-sent.
        for symbol, idea in list(self.account.open.items()):
            if idea.intent_id is None:
                continue
            status = self.knowledge.intent_status(idea.intent_id)
            if status in {"failed", "skipped", "rejected"}:
                px = self.last_price.get(symbol, idea.entry)
                self.paper.flatten(symbol, px, now, reason=f"intent_{status}")
                if symbol in self.account.open:  # twin may not have existed
                    self.account.on_flat(symbol)
                out.append({"event": "idea_freed", "symbol": symbol, "reason": f"intent_{status}"})
        raw = self.knowledge.meta("exchange_state")
        if not raw:
            return out
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            return out
        at = state.get("at")
        try:
            state_at = datetime.fromisoformat(str(at).replace("Z", "+00:00")) if at else None
        except ValueError:
            state_at = None
        if state_at is None or (now - state_at).total_seconds() > self.EXCHANGE_STATE_MAX_AGE_S:
            return out
        # 2) equity from the wallet
        equity = state.get("equity")
        if equity not in (None, ""):
            try:
                eq = Decimal(str(equity))
            except ArithmeticError:
                eq = None
            if eq is not None and eq > 0 and (
                self.account.equity != eq or not self.account.equity_source.startswith("exchange")
            ):
                self.account.set_equity(eq, source=f"exchange:{self.user_mode}", now=now)
                out.append({"event": "equity", "equity": str(eq), "source": self.user_mode})
        # 3) venue flat while our filled twin is open → the venue closed it.
        #    Only after the venue has *shown* the position (or a fill) for this idea:
        #    a twin the tape "filled" while our real limit is still queued is not
        #    closed (audit B3: that flatten used to cancel the live entry).
        venue_open = {str(p.get("symbol")) for p in state.get("positions") or [] if p.get("symbol")}
        for symbol in venue_open:
            self._venue_seen.add(symbol)
        for fill in state.get("fills") or []:
            sym = str(fill.get("symbol") or "")
            if sym:
                self._venue_seen.add(sym)
        for symbol in list(self.account.open):
            if symbol in venue_open:
                continue
            if symbol not in self._venue_seen:
                continue
            twins = [p for p in self.paper.open_for(symbol, source="demo") if p.state == "open"]
            for twin in twins:
                if twin.filled_at is None:
                    continue
                if (state_at - twin.filled_at).total_seconds() < self.VENUE_FLAT_GRACE_S:
                    continue
                px = self.last_price.get(symbol, twin.entry_px or twin.limit_px)
                self.paper.flatten(symbol, px, now, reason="venue_flat")
                out.append({"event": "venue_flat", "symbol": symbol})
            self._venue_seen.discard(symbol)
        return out

    CALIBRATION_REFRESH_S = 600.0

    def _refresh_calibration(self, now: datetime) -> None:
        """Per-class Wilson stats from filled shadow paper trades, every 10 minutes."""
        if (
            self._calibration_at is not None
            and (now - self._calibration_at).total_seconds() < self.CALIBRATION_REFRESH_S
        ):
            return
        self._calibration_at = now
        rows = self.knowledge.paper_trades(source="shadow")
        self._calibration = class_stats(rows)
        if self._calibration:
            self._ui_put("calibration", to_meta(self._calibration))
        self._refresh_drift(rows, now)

    # --- drift (4.19.2 / contour C): Page-Hinkley on the champion's error series --------
    DRIFT_WINDOW = 200
    DRIFT_MIN_N = 40

    def _refresh_drift(self, rows: Sequence[Mapping[str, Any]], now: datetime) -> None:
        """Errors = filled shadow trades with r_net ≤ 0, in close order. A detected
        increase in the error rate is drift: the live target risk is cut to 0.5%
        (`risk/drift_cut`) until the window clears. Never raises risk."""
        closed = [
            r for r in rows
            if r.get("entry_px") not in (None, "") and r.get("r_net") not in (None, "")
            and r.get("closed_at")
        ]
        closed.sort(key=lambda r: str(r["closed_at"]))
        errors = [1 if Decimal(str(r["r_net"])) <= 0 else 0 for r in closed[-self.DRIFT_WINDOW:]]
        was = self.drift_active
        if len(errors) < self.DRIFT_MIN_N:
            self.drift_active = False
            result = None
        else:
            result = PageHinkley().run(errors)
            self.drift_active = result.drift
        if self.knowledge.available():
            self._ui_put(
                "drift",
                json.dumps(
                    {
                        "at": now.isoformat(),
                        "n": len(errors),
                        "drift": self.drift_active,
                        "t": None if result is None else result.t,
                        "target_risk": str(self.effective_target_risk()),
                    }
                ),
            )
        if was != self.drift_active and self.knowledge.available():
            self.knowledge.set_meta(
                "drift_last_change",
                json.dumps({"at": now.isoformat(), "drift": self.drift_active}),
            )

    def effective_target_risk(self) -> Decimal:
        return target_after_drift(drift=self.drift_active, base=self.risk_config.target_risk_pct)

    def _reload_instruments(self) -> None:
        """Signer refreshed instruments-info from the venue → registry rows (D-04)."""
        raw = self.knowledge.meta("instruments_snapshot")
        if not raw or raw == self._instruments_seen:
            return
        self._instruments_seen = raw
        try:
            snap = json.loads(raw)
        except json.JSONDecodeError:
            return
        n = self.instruments.merge_snapshot(snap)
        for symbol in list(self.refused_symbols):
            if self.instruments.has(symbol):
                del self.refused_symbols[symbol]
        if n and self.knowledge.available():
            self._ui_put("instruments_loaded", str(n))

    def _reload_risk_config(self) -> None:
        """Operator saved a new RiskConfig: apply to new intents only (open ideas keep theirs)."""
        cfg = load_risk_config(self.knowledge)
        if cfg.config_id == self.risk_config.config_id:
            return
        self.risk_config = cfg
        self.account.config = cfg
        self.account.risk.max_open = cfg.max_open_positions
        assert self.account.halts is not None
        self.account.halts.day_limit = cfg.day_halt
        self.account.halts.week_limit = cfg.week_halt
        self.account.halts.peak_limit = cfg.peak_kill
        self.trail = TrailEngine(mode=cfg.trail_mode)

    # --- paper (W3) ----------------------------------------------------------------
    def _submit_paper(
        self,
        row: Touch,
        zone: Zone,
        known_zones: tuple[Zone, ...],
        *,
        idea: str,
        side: str,
        wick_extreme: Decimal,
        now: datetime,
        source: str,
        tag: str,
    ) -> str | None:
        """Same geometry as the live strategy, sized from the account, no EV gate:
        the shadow measures what the edge is worth *after* costs, it does not filter."""
        inst = self._instrument_for(row_symbol := zone.symbol)
        tick = inst.tick
        away = self.config.bounce_away_ticks
        st = self.state_for(row_symbol)
        try:
            if idea == "spring":
                structural = stop_behind_wick(zone, wick_extreme, tick, away, side=side)
            else:
                structural = stop_behind(zone, tick, away, side=side)
            spread = st.book.spread() if st.book.ready else None
            smart = initial_stop(
                side=side,
                structural=structural,
                tick=tick,
                atr=self._atr_for(st),
                spread=spread,
                zones=[z for z in known_zones if z.zone_id != zone.zone_id],
                mode=self.risk_config.stop_mode,
            )
            stop = smart.stop
        except ValueError:
            return None
        if (side == "buy" and row.trade_px <= stop) or (side == "sell" and row.trade_px >= stop):
            return None
        target = opposing_target(known_zones, side=side, entry=row.trade_px, symbol=row_symbol)
        tp = take_profit(side, row.trade_px, stop, target, idea="bounce")
        if tp is None:
            r = abs(row.trade_px - stop)
            tp = row.trade_px + 2 * r if side == "buy" else row.trade_px - 2 * r
        cfg = self.risk_config
        lev = min(cfg.max_lev, inst.max_lev)
        decision = size_position(
            equity=self.account.equity,
            entry=row.trade_px,
            stop=stop,
            lev=lev,
            target_risk=self.effective_target_risk(),
            deposit_share=cfg.deposit_share_per_trade,
            qty_step=inst.qty_step,
            min_qty=inst.min_qty,
            min_notional=inst.min_notional,
            max_lev=cfg.max_lev,
        )
        qty = decision.qty if decision.action == "accept" else inst.min_qty
        pid = f"{row.touch_id}:{source}"
        if pid in self.paper.positions:
            return pid
        self.paper.submit(
            paper_id=pid,
            touch_id=row.touch_id,
            symbol=row_symbol,
            side=side,  # type: ignore[arg-type]
            limit_px=row.trade_px,
            qty=qty,
            stop=stop,
            tp=tp,
            tick=tick,
            now=now,
            valid_for=timedelta(
                minutes=TF_MINUTES.get(self.config.working_tf, 15) * self.INTENT_TTL_BARS
            ),
            source=source,  # type: ignore[arg-type]
            tag=tag,
            funding_interval_min=inst.funding_interval_min,
            structural=structural,
            stop_components=smart.components,
            labels={
                "cav_label": row.cav_label,
                "zlg_label": row.gesture,
                "symbol": row_symbol,
                "zone_side": zone.side,
                "btc_regime": row.btc_regime,
            },
        )
        return pid

    def _oms(self, pos: PaperPosition, kind: str, now: datetime, **fields: Any) -> None:
        """Mirror a decision on a demo/live twin to the gateway via oms_commands.

        The desk decides once (paper twin), the signer executes on the venue. Shadow and
        fade twins never reach the venue.
        """
        if pos.source != "demo" or not self.knowledge.available():
            return
        if self.user_mode not in {"demo", "live"}:
            return
        self.knowledge.enqueue_oms(
            kind=kind,
            symbol=pos.symbol,
            payload={
                "paper_id": pos.paper_id,
                "touch_id": pos.touch_id,
                "side": pos.side,
                **fields,
            },
            created_ts=now.isoformat(),
        )

    # Bybit linear funding clamp is ±0.375%/8h (instruments-info upperFundingRate on
    # BTCUSDT in the docs example). "Extreme" = the 95th percentile of THIS symbol's
    # own observed |rate| once ≥ 20 prints exist; before that no rate is extreme
    # (unknown is not a veto). Provenance: data, self-calibrating.
    FUNDING_MIN_N = 20

    # --- fragility (3.15.5): OI peak × crowded funding × thin book -----------------
    OI_HIST_STEP = timedelta(minutes=5)
    OI_HIST_KEEP = timedelta(days=30)
    FRAGILITY_THIN_Z = Decimal("-1")

    def _sample_oi_history(self, symbol: str, when: datetime, level: Decimal) -> None:
        """One OI sample per 5 minutes per symbol, 30 days, persisted (meta oi_hist:*)."""
        hist = self._oi_hist.setdefault(symbol, [])
        if hist and when - hist[-1][0] < self.OI_HIST_STEP:
            return
        hist.append((when, level))
        cutoff = when - self.OI_HIST_KEEP
        while hist and hist[0][0] < cutoff:
            hist.pop(0)
        if self.knowledge.available():
            self._ui_put(
                f"oi_hist:{symbol}",
                json.dumps([[ts.isoformat(), str(lv)] for ts, lv in hist]),
            )

    def _load_oi_history(self) -> None:
        for key, raw in self.knowledge.meta_prefix("oi_hist:").items():
            symbol = key.split(":", 1)[1]
            try:
                rows = json.loads(raw)
                self._oi_hist[symbol] = [
                    (datetime.fromisoformat(ts), Decimal(str(lv))) for ts, lv in rows
                ]
            except (json.JSONDecodeError, ValueError, TypeError, ArithmeticError):
                continue

    def _oi_peak(self, symbol: str) -> bool | None:
        hist = self._oi_hist.get(symbol) or []
        if len(hist) < self.FUNDING_MIN_N:
            return None
        levels = sorted(lv for _ts, lv in hist)
        p95 = levels[min(len(levels) - 1, int(0.95 * (len(levels) - 1)))]
        return hist[-1][1] >= p95

    def _funding_tail(self, symbol: str) -> tuple[bool | None, bool | None]:
        """(top-5% positive → longs pay, crowd long; bottom-5% → shorts pay, crowd short)."""
        rate = self.funding.get(symbol)
        hist = self._funding_hist.get(symbol) or []
        if rate is None or len(hist) < self.FUNDING_MIN_N:
            return None, None
        xs = sorted(hist)
        p95 = xs[min(len(xs) - 1, int(0.95 * (len(xs) - 1)))]
        p5 = xs[max(0, int(0.05 * (len(xs) - 1)))]
        return (rate >= p95 and rate > 0), (rate <= p5 and rate < 0)

    def _thin_book(self, st: SymbolState) -> bool | None:
        """Depth near the touch against the ОКО Passport norm (robust z < −1 = thin)."""
        book = st.book_pre or st.book
        if not book.ready or st.last_touch is None:
            return None
        passport = self.oko.passport_for(st.symbol)
        px = str(st.last_touch.trade_px)
        depth = book.depth_near("bid", px, self.config.prs_delta_ticks) + book.depth_near(
            "ask", px, self.config.prs_delta_ticks
        )
        z = passport.depth.z(depth)
        if z is None:
            return None
        return z < self.FRAGILITY_THIN_Z

    def _fragility(self, st: SymbolState) -> dict[str, Any]:
        oi_peak = self._oi_peak(st.symbol)
        top5, bottom5 = self._funding_tail(st.symbol)
        thin = self._thin_book(st)
        return {
            "oi_peak": oi_peak,
            "funding_top5": top5,
            "funding_bottom5": bottom5,
            "thin_book": thin,
            "forbid_long": forbid_new_long(oi_peak=oi_peak, funding_top5=top5, thin_book=thin),
            "forbid_short": forbid_new_short(
                oi_peak=oi_peak, funding_bottom5=bottom5, thin_book=thin
            ),
        }

    def _funding_extreme(self, symbol: str) -> bool:
        rate = self.funding.get(symbol)
        if rate is None:
            return False
        hist = self._funding_hist.setdefault(symbol, [])
        if not hist or hist[-1] != rate:
            hist.append(rate)
            if len(hist) > 2000:
                del hist[: len(hist) - 2000]
        if len(hist) < self.FUNDING_MIN_N:
            return False
        xs = sorted(abs(x) for x in hist)
        p95 = xs[min(len(xs) - 1, int(0.95 * (len(xs) - 1)))]
        return abs(rate) > p95

    def _atr_for(self, st: SymbolState) -> Decimal | None:
        work = [b for b in st.bars if b.tf == self.config.working_tf]
        return atr_of(work[-15:]) if len(work) >= 2 else None

    def _trail_state(self, pos: PaperPosition) -> TrailState:
        stt = self._trails.get(pos.paper_id)
        if stt is None:
            assert pos.entry_px is not None
            # After a restart the twin carries its trailed stop and its initial stop:
            # 1R must come from the initial one, the phase from the half flag.
            stt = TrailState(
                side=pos.side,
                entry=pos.entry_px,
                stop=pos.stop,
                tick=pos.tick,
                initial_stop=pos.initial_stop,
            )
            self._trails[pos.paper_id] = stt
        return stt

    def _venue_qty(self, symbol: str) -> Decimal | None:
        """Size the venue reports for `symbol` (REST truth), None when unknown."""
        raw = self.knowledge.meta("exchange_state") if self.knowledge.available() else None
        if not raw:
            return None
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            return None
        for p in state.get("positions") or []:
            if str(p.get("symbol")) == symbol:
                try:
                    return Decimal(str(p.get("size") or "0"))
                except ArithmeticError:
                    return None
        return None

    def _trail_on_bar(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        """§7: every closed working bar moves the stops of open paper positions.

        Structure trail after the +1R half; venue-style trailing after an impulse bar;
        close-based soft exit beyond the structural level (hybrid mode). All monotone.
        """
        out: list[dict[str, Any]] = []
        work = [b for b in st.bars if b.tf == self.config.working_tf][-60:]
        last_px = self.last_price.get(st.symbol, bar.close)
        for pos in list(self.paper.open_for(st.symbol)):
            if pos.state != "open":
                continue
            if (
                self.risk_config.stop_mode == "hybrid"
                and pos.structural is not None
                and soft_exit(side=pos.side, structural=pos.structural, bar=bar)
            ):
                self._oms(pos, "flatten", bar.close_ts, reason="soft_exit")
                self.paper.soft_exit(pos.paper_id, bar.close, bar.close_ts)
                out.append({"event": "trail", "paper_id": pos.paper_id, "action": "soft_exit"})
                self._trails.pop(pos.paper_id, None)
                continue
            stt = self._trail_state(pos)
            if pos.half_taken and not stt.half_taken:
                self.trail.on_half(stt)
            for action in self.trail.on_bar(stt, work, last_px=last_px):
                if action.kind == "amend_stop" and action.new_stop is not None:
                    if self.paper.set_stop(pos.paper_id, action.new_stop, reason=action.reason):
                        out.append(
                            {
                                "event": "trail",
                                "paper_id": pos.paper_id,
                                "action": "amend_stop",
                                "stop": str(action.new_stop),
                                "reason": action.reason,
                            }
                        )
                        self._oms(pos, "amend_stop", bar.close_ts, stop=str(action.new_stop),
                                  reason=action.reason)
                elif action.kind == "exchange_trailing" and action.trailing_distance:
                    if self.paper.arm_trailing(
                        pos.paper_id, action.trailing_distance, reason=action.reason
                    ):
                        out.append(
                            {
                                "event": "trail",
                                "paper_id": pos.paper_id,
                                "action": "exchange_trailing",
                                "distance": str(action.trailing_distance),
                                "reason": action.reason,
                            }
                        )
                        self._oms(
                            pos, "set_trailing", bar.close_ts,
                            distance=str(action.trailing_distance),
                            active_price=(
                                None if action.active_price is None else str(action.active_price)
                            ),
                            reason=action.reason,
                        )
        for pid in [p for p in self._trails if p not in self.paper.positions]:
            del self._trails[pid]
        return out

    def _on_paper_close(self, pos: PaperPosition) -> None:
        """Persist the closed paper trade, mirror it into the journal, move the demo account."""
        payload = pos.to_payload()
        if self.knowledge.available():
            self.knowledge.put_paper_trade(payload)
            row = self.knowledge.get_journal_touch(pos.touch_id)
            if row is not None:
                paper = row.get("paper") if isinstance(row.get("paper"), dict) else {}
                paper[pos.source] = {
                    "paper_id": pos.paper_id,
                    "filled": pos.entry_px is not None,
                    "exit_reason": pos.exit_reason,
                    "r_net": payload["r_net"],
                    "r_gross": payload["r_gross"],
                    "mae_r": payload["mae_r"],
                    "mfe_r": payload["mfe_r"],
                    "pnl_net": str(pos.pnl_net()),
                    "fees": str(pos.fees),
                    "funding": str(pos.funding),
                    "hold_s": payload["hold_s"],
                }
                row["paper"] = paper
                day = row_day_utc(row)
                self.knowledge.put_journal_touch(pos.touch_id, row)
                if day:
                    persist_day(self.knowledge, day)
        if pos.source == "demo":
            when = pos.closed_at or datetime.now(tz=UTC)
            if pos.entry_px is not None and not self.account.equity_source.startswith("exchange"):
                # Paper P&L moves the account only while the account IS paper. With a
                # venue wallet as the source the realized P&L is already in that number.
                self.account.apply_pnl(
                    pnl=pos.realized, fees=pos.fees, funding=pos.funding, now=when, source="paper"
                )
            # (3) The twin is the desk's decision; the venue must follow it. flatten on
            # the venue = cancel resting entries + close whatever position is left, so a
            # stop/TP/time/expiry/veto here never leaves an orphan order or position.
            if pos.exit_reason not in {"soft", "b_veto"}:  # those already queued flatten
                self._oms(pos, "flatten", when, reason=f"twin_{pos.exit_reason}")
            self.account.on_flat(pos.symbol)

    # --- sizing + EV gate (D-06, D-11, D-12, D-16, D-38) -----------------------
    INTENT_TTL_BARS = 2

    def _instrument_for(self, symbol: str) -> Instrument:
        if self.instruments.has(symbol):
            return self.instruments.get(symbol)
        # Legacy single-tick fixtures: lot facts are the test fixture's, marked so.
        return Instrument.fixture(symbol, tick=self.tick_for(symbol))

    def _size_and_gate(
        self,
        intent: Intent,
        symbol: str,
        now: datetime,
        labels: Mapping[str, Any] | None = None,
    ) -> tuple[Intent | None, dict[str, Any]]:
        """Concrete qty from the account and a fee/funding EV check. Never 0.001."""
        cfg = self.risk_config
        inst = self._instrument_for(symbol)
        labels = dict(labels or {})
        info: dict[str, Any] = {"send_skip": None}
        if self.entries_paused:
            info["send_skip"] = "paused_by_operator"
            return None, info
        ok, why = self.account.allow_entry(symbol)
        if not ok:
            info["send_skip"] = why
            return None, info
        lev = min(cfg.max_lev, inst.max_lev)
        decision = size_position(
            equity=self.account.equity,
            entry=intent.entry,
            stop=intent.stop,
            lev=lev,
            target_risk=self.effective_target_risk(),
            deposit_share=cfg.deposit_share_per_trade,
            qty_step=inst.qty_step,
            min_qty=inst.min_qty,
            min_notional=inst.min_notional,
            max_lev=cfg.max_lev,
        )
        info["sizing"] = {
            "action": decision.action,
            "reason": decision.reason,
            "qty": str(decision.qty),
            "lev": str(decision.lev),
            "margin": str(decision.margin),
            "risk_usdt": str(decision.risk_usdt),
            "risk_frac": str(decision.risk_frac),
            "binding": decision.binding,
            "equity": str(self.account.equity),
            "equity_source": self.account.equity_source,
            "config_id": cfg.config_id,
        }
        if decision.action != "accept":
            info["send_skip"] = f"size:{decision.binding}"
            return None, info
        qty = inst.round_qty(decision.qty * intent.size_mult)
        qok, qwhy = inst.qty_ok(qty, intent.entry)
        if not qok:
            info["send_skip"] = f"size_mult:{qwhy}"
            return None, info
        ev = ev_evaluate(
            qty=qty,
            entry=intent.entry,
            stop=intent.stop,
            tick=inst.tick,
            role="maker",
            funding_rate=self.funding.get(symbol),
            funding_interval_min=inst.funding_interval_min,
            fee_multiple_min=cfg.fee_multiple_min,
        )
        info["ev"] = {
            "ok": ev.ok,
            "reason": ev.reason,
            "r_gross": str(ev.r_gross),
            "fees": str(ev.fees),
            "funding": str(ev.funding),
            "slippage": str(ev.slippage),
            "fee_multiple": None if ev.fee_multiple is None else str(ev.fee_multiple),
            "r_net_1r": str(ev.r_net_1r),
            "r_net_2r": str(ev.r_net_2r),
            "r_net_3r": str(ev.r_net_3r),
            "breakeven_winrate": (
                None if ev.breakeven_winrate is None else str(ev.breakeven_winrate)
            ),
        }
        if not ev.ok:
            info["send_skip"] = "ev:fee_gt_r"
            return None, info
        # D-03: a class the paper record has refuted (Wilson upper bound of its net
        # winrate below this trade's break-even) is not sent live. It keeps trading
        # on paper so the verdict can flip with data.
        key = class_key(idea=intent.tag, cav=labels.get("cav_label"), zlg=labels.get("zlg_label"))
        stat = self._calibration.get(key)
        info["calibration"] = None if stat is None else stat.to_payload()
        if ev.breakeven_winrate is not None and refuted(stat, breakeven=ev.breakeven_winrate):
            info["send_skip"] = f"calib:{key}"
            return None, info
        ttl = timedelta(minutes=TF_MINUTES.get(self.config.working_tf, 15) * self.INTENT_TTL_BARS)
        sized = intent.model_copy(
            update={
                "qty": qty,
                "size_mult": Decimal("1"),  # cut already applied to qty; signer must not double-cut
                "lev": lev,
                "risk_config_id": cfg.config_id,
                "valid_until": (now + ttl).isoformat(),
            }
        )
        info["size_mult_applied"] = str(intent.size_mult)
        return sized, info

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
            if len(self._width_history) > self.WIDTH_HISTORY_MAX:
                del self._width_history[: len(self._width_history) - self.WIDTH_HISTORY_MAX]
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
            out.extend(self.tick(when, force_flush=False))
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
            if not self.instrument_ok(event.symbol):
                out.append(_refused(event.symbol))
                continue
            if event.stream == "trades":
                built = zones_for_trade(self, event, extras)
                self.persist_zones(built)
                out.extend(self.on_event(event, built))
            else:
                out.extend(self.on_event(event))
        if now is not None:
            advance(require_utc(now))
        return out


def _refused(symbol: str) -> dict[str, Any]:
    """No tick/lot facts for this symbol: refuse loudly instead of assuming 0.1."""
    return {"event": "refused", "symbol": symbol, "reason": "instrument_unknown"}


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
    # Same rank as prints: order between a print and a liquidation at one ts is
    # not a law. bar_close dicts stay at 9, after every print (unchanged).
    "liquidation": 8,
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


def _record_adds_from_diff(
    st: SymbolState,
    ts: datetime,
    before: dict[tuple[str, Decimal], Decimal],
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
) -> None:
    """O(diff): a positive size delta at a price the diff touched is a ZLG BookAdd; a
    negative one is a BookPull. The gesture nets them (survived liquidity)."""
    for side, rows in (("bid", bids), ("ask", asks)):
        levels = st.book.levels(side)  # type: ignore[arg-type]
        for px_s, _sz in rows:
            px = Decimal(px_s)
            delta = levels.get(px, Decimal("0")) - before.get((side, px), Decimal("0"))
            hit: Literal["bid", "ask"] = "bid" if side == "bid" else "ask"
            if delta > 0:
                st.adds.append(BookAdd(ts=ts, side=hit, px=px, qty=delta))
            elif delta < 0:
                st.pulls.append(BookPull(ts=ts, side=hit, px=px, qty=-delta))


def _f(value: float | None) -> str | None:
    """Journal text for an ОКО probability / trust. None stays None."""
    return None if value is None else f"{value:.4f}"


def _levels(rows: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(rows, list | tuple):
        return ()
    out: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        out.append((str(row[0]), str(row[1])))
    return tuple(out)

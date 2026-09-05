"""Per-symbol 24/7 state machine. No global 'all symbols then jury' pass.

IDLE → ARM_ZLG → LABEL_ZLG → JURY. Send only inside the desk window
when user_mode is demo|live and jury is ACCORD. Shadow always writes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from capitalizator.book.reconstruct import Book, BookDirty
from capitalizator.book.validate import validate
from capitalizator.book.wall_watch import WallWatch, last_wall_kind, pulled_without_print
from capitalizator.btc.break_def import Break
from capitalizator.btc.regime import BtcRegime
from capitalizator.btc.veto import BtcVeto
from capitalizator.card.build import from_news as card_from_news
from capitalizator.card.draft import pending_card
from capitalizator.card.first_fact import resolve as resolve_first_fact
from capitalizator.card.live import CardLive, card_is_fresh, touch_line
from capitalizator.card.volume import snapshot as volume_snapshot
from capitalizator.champion.calibrate import (
    ClassStat,
    class_key,
    class_stats,
    eligible_windows,
    k_atr_by_window,
    loss_series_by_window,
    median_hold_hours,
    refuted,
    to_meta,
)
from capitalizator.champion.calibrate import lookup as calibration_lookup
from capitalizator.champion.drift import PageHinkley
from capitalizator.champion.exam import exam
from capitalizator.champion.shadow_day import (
    challenger_on,
    challenger_tag,
    persist_day,
    row_day_utc,
)
from capitalizator.desk.bars import FEATURE_TFS, TF_MINUTES, BarBuilder, builder_tfs
from capitalizator.desk.paper_gates import snapshot as paper_gates_snapshot
from capitalizator.desk.pictures import needs_new_card, picture_for
from capitalizator.exec.ev_gate import evaluate as ev_evaluate
from capitalizator.exec.failed_break import sweep_wick
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.exec.fvg_mark import fvg_present
from capitalizator.exec.ideas import classify as classify_idea
from capitalizator.exec.ideas import opposite as opposite_side
from capitalizator.exec.ideas import shadow_tag as idea_shadow_tag
from capitalizator.exec.ideas import side_for
from capitalizator.exec.manage import TradeManager
from capitalizator.exec.paper import PaperEngine, PaperPosition
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
from capitalizator.hyexec.adwin import after_hour_dd
from capitalizator.hyexec.alerts import stamp as stamp_hyexec
from capitalizator.hyexec.expand import expand_ok, take_at_1r
from capitalizator.hyexec.score_exit import SCORE_DROP
from capitalizator.hyexec.features import NAMES as HYEXEC_FEATURE_NAMES
from capitalizator.hyexec.features import FeatureRow, build_features
from capitalizator.hyexec.pace import pyramid_ok
from capitalizator.hyexec.sizing import desk_step, effective_risk
from capitalizator.hyexec.timing import may_send
from capitalizator.hyexec.window_halt import WindowHalt
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
from capitalizator.memory.revive import PENDING, load_pending
from capitalizator.news_macro.from_intel import calendar_from_intel, claims_from_intel
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.rules import MacroRules
from capitalizator.news_macro.sentiment import decide as sentiment_decide
from capitalizator.news_macro.unlocks import Unlocks
from capitalizator.oko.eye import OkoEye, OkoWindow
from capitalizator.oko.footprint import FINGERPRINT_LEN as OKO_FINGERPRINT_LEN
from capitalizator.oko.forecast import Sample as OkoSample
from capitalizator.oko.forecast import class_key as oko_class_key
from capitalizator.oko.retina import RawWindow
from capitalizator.oko.shadow import FINGERPRINT_LEN as OKO_SHADOW_FP_LEN
from capitalizator.ops.decision_trace import DecisionTrace, intel_atom
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.latency import decision_report
from capitalizator.ops.phase import breakout_enabled
from capitalizator.ops.product import DEFAULT_MODE, META_HELLO
from capitalizator.ops.uptime import UptimeTracker
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
from capitalizator.risk.correlation import CorrelationGuard, returns_from_closes
from capitalizator.risk.drift_cut import target_after_drift
from capitalizator.risk.schema import Intent, reject_forbidden_keys
from capitalizator.risk.session import cpi_day, us_data_known_at
from capitalizator.risk.sessions import SessionPolicy, WindowState
from capitalizator.risk.sizing import size_position
from capitalizator.screener.universe import load_desk_universe
from capitalizator.tape.classify import TapeClassifier
from capitalizator.tape.liquidity import snapshot as liquidity_snapshot
from capitalizator.types import MarketEvent, require_utc
from capitalizator.whales.fragility import forbid_new_long, forbid_new_short
from capitalizator.whales.no_single import sole_whale
from capitalizator.zlg.gesture import ZLG, BookAdd, BookPull
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import MAP_VOTE_METHODS
from capitalizator.zones.map import ZoneMap
from capitalizator.zones.model import Bar, Zone
from capitalizator.zones.pair import confirm_label, vote_tf

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
    feature_bars: list[Bar] = field(default_factory=list)
    last_features: FeatureRow | None = None
    zlg_card: CardLive | None = None
    oko_window: OkoWindow | None = None
    oi: list[tuple[datetime, Decimal]] = field(default_factory=list)
    funding: list[tuple[datetime, Decimal]] = field(default_factory=list)
    liquidations: list[MarketEvent] = field(default_factory=list)


@dataclass
class BtcBus:
    """Read-only BTC bus for alts. Writer is the BTC symbol loop."""

    regime: str | None = None
    # HTF direction behind `regime == "trend"`: long | short. None in a box / unknown.
    direction: str | None = None
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
        policy: SessionPolicy | None = None,
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
        # Session policy (infra/sessions.yaml): which idea may be SENT in which UTC
        # window, size multiplier, stop buffer k_atr, intent budget, symbol policy,
        # blackouts, funding settlement guard. Shadow / fade twins ignore it (W3).
        self.policy = policy if policy is not None else SessionPolicy.load()
        # D-09/D-10/D-13: one Account owns equity, open ideas, halts and the
        # per-session budget; RiskEngine/Halts are its members, not orphans.
        self.risk_config = load_risk_config(knowledge)
        self.account = Account.load(knowledge, self.risk_config)
        self.risk = self.account.risk
        self.halts = self.account.halts
        assert self.halts is not None
        self.window_halt = WindowHalt(start_equity=self.halts.day_start)
        if self.halts.peak > self.window_halt.peak:
            self.window_halt.peak = self.halts.peak
        self.window_halt.note_window("init", self.account.equity)
        self._hour_start_at: datetime | None = None
        self._hour_start_equity = self.account.equity
        self._load_hour_start()
        self.hyexec_model_go: bool | None = None
        self.funding: dict[str, Decimal] = {}
        self._funding_hist: dict[str, list[Decimal]] = {}
        self._oi_hist: dict[str, list[tuple[datetime, Decimal]]] = {}
        # Settlement clock and 24h turnover per symbol from the ticker stream.
        self.next_funding: dict[str, datetime] = {}
        self.turnover: dict[str, Decimal] = {}
        self.macro = MacroRules(enabled=True)
        self.strategy = BounceStrategy(
            risk=self.risk,
            halts=self.halts,
            session=self.policy,
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
        self.entries_paused = knowledge.available() and knowledge.meta("entries_paused") == "1"
        self._instruments_seen: str | None = None
        self._calibration: dict[str, ClassStat] = {}
        self._calibration_at: datetime | None = None
        self.drift_active = False
        self._sentiment_at: datetime | None = None
        self._sentiment_mult = Decimal("1")
        self._sentiment_reason = "sentiment_ok"
        self._oko_samples_cache: tuple[Any, list[OkoSample], set[str]] | None = None
        self._k_atr_calibrated: dict[str, Decimal] = {}
        self._hold_hours: dict[str, Decimal] = {}
        # window → ISO time the drift was detected; cleared by the operator only.
        # ack_n: loss-series length at the last release (detection restarts after it).
        self._window_drift: dict[str, str] = {}
        self._drift_ack_n: dict[str, int] = {}
        self._drift = PageHinkley(delta=0.05, threshold=8.0)
        # Day screen cache: (minute, frozenset) — the scan walks every symbol's bars.
        self._screen_cache: tuple[datetime, frozenset[str]] | None = None
        # Live funding intervals from the ticker; re-applied after an instruments-info merge.
        self._live_funding_interval: dict[str, int] = {}
        self._correlation_at: datetime | None = None
        self.oko = OkoEye(working_tf=self.config.working_tf)
        # F0 tape uptime, tracked from the events this process already streams
        self.uptime = UptimeTracker.from_json(
            knowledge.meta("tape_uptime") if knowledge.available() else None
        )
        self._uptime_dirty = False
        self.shadow_writes: list[dict[str, Any]] = []
        self.last_price: dict[str, Decimal] = {}
        # Symbols the venue has shown a position or a fill for (venue_flat needs proof
        # the venue ever held the idea before it may close the twin).
        self._venue_seen: set[str] = set()
        # Naked venue stop: symbol → {since, amended, flattened}. Clock is the
        # signer's reconcile `at`, not the desk tick — same snapshot must not
        # increment a retry or flatten (audit SL-ack).
        self._sl_ack: dict[str, dict[str, Any]] = {}
        self._paper_dirty = False
        if knowledge.available():
            self.oko.load(knowledge)
            # a corrupt organ is dropped, and the operator sees which one (Учёба block)
            knowledge.set_meta(
                "oko_load_errors",
                json.dumps(self.oko.load_errors, ensure_ascii=False, sort_keys=True),
            )
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
            raw_sl = knowledge.meta("sl_ack")
            if raw_sl:
                try:
                    loaded = json.loads(raw_sl)
                except json.JSONDecodeError:
                    loaded = None
                if isinstance(loaded, dict):
                    self._sl_ack = {
                        str(sym): dict(body)
                        for sym, body in loaded.items()
                        if isinstance(body, dict)
                    }
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
        # 8s liquidity blob, stamped at ZLG. book_history slides after LABEL_ZLG.
        self._liquidity_stamped: dict[str, dict[str, Any]] = {}
        self._ui_pending: dict[str, str] = {}
        self._ui_last_flush: datetime | None = None
        self._ui_last_wall_flush: datetime | None = None
        self._ui_book_published: set[str] = set()
        self.zone_cache: dict[str, tuple[tuple[Any, ...], tuple[Zone, ...]]] = {}
        self._persisted_zone_ids: dict[str, frozenset[str]] = {}
        self._last_zone_retire: datetime | None = None
        self._last_settle: datetime | None = None
        if knowledge.available():
            self._reload_instruments()
            self._load_oi_history()
            self._load_drift()

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
                    tfs=builder_tfs(self.config.structure_tfs),
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

    def _publish_decision_latency(self) -> None:
        if not self.knowledge.available():
            return
        try:
            report = decision_report(self.knowledge.journal_rows())
        except ValueError:
            return
        self.knowledge.set_meta("latency_decision", json.dumps(report, sort_keys=True))

    def _ui_due(self, now: datetime) -> bool:
        return (
            self._ui_last_flush is None
            or (now - self._ui_last_flush).total_seconds() >= self.UI_FLUSH_S
        )

    def _book_ui_payload(self, st: SymbolState, when: datetime) -> str:
        bids = sorted(
            ((str(px), str(sz)) for px, sz in st.book.levels("bid").items()),
            key=lambda row: Decimal(row[0]),
            reverse=True,
        )[:20]
        asks = sorted(
            ((str(px), str(sz)) for px, sz in st.book.levels("ask").items()),
            key=lambda row: Decimal(row[0]),
        )[:20]
        return json.dumps(
            {"symbol": st.symbol, "bids": bids, "asks": asks, "ts": when.isoformat()},
            sort_keys=True,
            ensure_ascii=False,
        )

    def _book_ui_empty(self, symbol: str) -> str:
        return json.dumps(
            {"symbol": symbol, "bids": [], "asks": [], "ts": None},
            sort_keys=True,
            ensure_ascii=False,
        )

    def _queue_ready_books(self, when: datetime, *, persist_empty: bool) -> None:
        """Last-value book on the same UI tick as last_price.

        Bybit (2026) pushes depth on its own stream (L50 ~20ms, L200 ~100ms),
        not as a side effect of public trades. Sharing `_ui_due` with last_price
        let BTC prints own the 0.5s clock so `book:{symbol}` never landed.
        A marked book-seq hole (`missing_stream`) must not keep last levels.
        A time-gap marker is not that: do not persist empty just because this tick
        has not yet seen a snapshot (that wiped the live 20-level book on the VPS).
        """
        for st in self.symbols.values():
            if st.book.ready:
                self._ui_book_published.add(st.symbol)
                self._ui_put(f"book:{st.symbol}", self._book_ui_payload(st, when))
            elif persist_empty and st.symbol in self._ui_book_published:
                self._ui_put(f"book:{st.symbol}", self._book_ui_empty(st.symbol))

    def flush_ui(self, now: datetime, *, force: bool = False) -> int:
        """Write last_price / book snapshots in one transaction, at most every 0.5s."""
        if (not self._ui_pending and not self._uptime_dirty) or not self.knowledge.available():
            return 0
        wall = datetime.now(tz=UTC)
        wall_due = (
            self._ui_last_wall_flush is None
            or (wall - self._ui_last_wall_flush).total_seconds() >= self.UI_FLUSH_S
        )
        if not force and not self._ui_due(now) and not wall_due:
            return 0
        if self._uptime_dirty:
            self._ui_pending["tape_uptime"] = self.uptime.to_json()
            self._uptime_dirty = False
        # Catch-up ticks (force=False) must not persist empty over last-value.
        self._queue_ready_books(now, persist_empty=force)
        n = len(self._ui_pending)
        self.knowledge.set_meta_many(self._ui_pending)
        self._ui_pending = {}
        self._ui_last_flush = now
        self._ui_last_wall_flush = wall
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
        # UI book is last-value on the shared flush tick (flush_ui). Do not gate
        # it on _ui_due: trades reset that clock and starved book:{symbol}.

    def _wall_threshold(self, symbol: str) -> Decimal | None:
        """One level is a wall when it is loud for *this* book.

        Mature Passport → `wall_depth_mult × median zone-side depth` of the symbol
        (the same measure ОКО normalises on). Before that → `wall_min_notional / px`.
        No price and no norm → None: nothing is a wall, nothing is a pull. The old
        constants (50 coins, then $3M for every symbol) made every DOGE level a wall
        and no alt level one.
        """
        passport = self.oko.passport_for(symbol)
        if passport.depth.mature:
            median = passport.depth.median()
            if median is not None and median > 0:
                return median * self.config.wall_depth_mult
        px = self.last_price.get(symbol)
        if px and px > 0:
            return self.config.wall_min_notional / px
        return None

    def _wall_for(self, symbol: str) -> WallWatch:
        threshold = self._wall_threshold(symbol)
        watch = self.walls.get(symbol)
        if watch is None:
            watch = WallWatch(symbol, min_size=threshold)
            self.walls[symbol] = watch
        else:
            watch.set_min_size(threshold)
        return watch

    def _prs_for(self, symbol: str) -> PRS:
        if symbol not in self.prs:
            self.prs[symbol] = PRS(tick_size=self.tick_for(symbol), config=self.config)
        return self.prs[symbol]

    def on_book(self, symbol: str, book: Book) -> None:
        self.state_for(symbol).book = book

    def _apply_book_event(self, st: SymbolState, event: MarketEvent) -> None:
        """Apply snapshot/diff from tape. Do not invent levels. Time-gaps do not wipe."""
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
            except BookDirty:
                # Official orderbook.200: snapshot first. No snapshot yet — do not
                # invent levels. Last sqlite value stays until snapshot / u=1.
                return
            except SeqFault:
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
                self._on_funding_payload(event.symbol, event.payload)
            if event.stream == "mark":
                self.paper.on_mark(event)
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
            # Time holes (ts_from/ts_to, recorder reconnect) are uptime law, not L2.
            # uptime.py: a book seq hole is not a time hole — the inverse holds.
            if event.stream == "gap" and not event.payload.get("missing_stream"):
                return [{"event": "gap", "symbol": event.symbol, "book_dirty": False}]
            st.book = Book(tick_size=str(self.tick_for(st.symbol)))
            return [{"event": event.stream, "symbol": event.symbol, "book_dirty": True}]
        raise ValueError(f"unknown stream: {event.stream!r}")

    def on_bar_close(self, bar: Bar) -> list[dict[str, Any]]:
        if bar.tf in FEATURE_TFS:
            return self._on_feature_bar(bar)
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
        if bar.tf in {self.config.mid_tf, self.config.htf, self.config.htf_d1}:
            self.publish_card(bar.symbol, bar.close_ts)
        elif bar.tf == self.config.working_tf and self.calendar:
            # D-21: TTL is 60s, so publishing only on 4h/1d closes left the card
            # stale 239 minutes out of 240. A working close refreshes a stale card
            # (a fresh one — e.g. just written by contour B — is kept).
            self._card_for(bar.symbol, bar.close_ts)
        trail_events: list[dict[str, Any]] = []
        if bar.tf == self.config.working_tf:
            trail_events = self._trail_on_bar(st, bar)
        jury_events: list[dict[str, Any]] = []
        if st.last_touch is not None and st.state == "LABEL_ZLG":
            zone = self.registry._zone_any(st.last_touch.zone_id)
            if zone is not None and bar.tf == vote_tf(zone.tf, self.config.structure_tfs):
                # Senior level votes on its junior TF; a 15m zone votes on 15m.
                jury_events = self._eval_cav_and_jury(st, bar)
        retired = self._retire_invalidated(st, bar)
        if bar.tf == self.config.working_tf or jury_events:
            return jury_events + trail_events + retired
        return retired

    def _on_feature_bar(self, bar: Bar) -> list[dict[str, Any]]:
        """1m/5m close: PIT features only. Not a zone, not a jury tick, no score."""
        st = self.state_for(bar.symbol)
        st.feature_bars.append(bar)
        del st.feature_bars[:-240]
        if st.bar_builder is not None:
            st.bar_builder.seed_closed((bar,))
        if bar.tf == "5m":
            st.last_features = build_features(
                bars_1m=[b for b in st.feature_bars if b.tf == "1m"],
                bars_5m=[b for b in st.feature_bars if b.tf == "5m"],
                bars_1h=[b for b in st.bars if b.tf == "1h"],
                as_of=bar.close_ts,
            )
        return [{"event": "hyexec_features", "symbol": bar.symbol, "tf": bar.tf}]

    def _note_hyexec(self, kind: str, *, symbol: str, now: datetime) -> None:
        if self.knowledge.available():
            stamp_hyexec(self.knowledge, kind=kind, symbol=symbol, at=now)

    def publish_card(self, symbol: str, now: datetime) -> CardLive:
        """Compute B labels and write claim b_card:SYMBOL. Never sends.

        Live intel (RSS announcements, classified titles) is merged into the
        calendar so a HACK/CPI/FOMC print can veto or cut. A sole whale claim
        is a hold — whales never enter.
        """
        bars = self.state_for(symbol).bars
        vol = volume_snapshot(bars)
        intel_cal = calendar_from_intel(self.knowledge, now=now)
        card = card_from_news(
            symbol=symbol,
            now=now,
            calendar=tuple(self.calendar) + intel_cal,
            volume=vol,
            bars=bars,
        )
        card = self._apply_author_pump(card, symbol, now, vol)
        card = self._apply_author_weights(card)
        if self.knowledge.available():
            since = (now - timedelta(hours=48)).isoformat()
            claims = claims_from_intel(self.knowledge.intel_items(since=since, limit=400))
            if sole_whale(claims) and card.bearing_verdict in {"propose", "cut_size"}:
                pluses = tuple(dict.fromkeys((*card.pluses, "whale_seen")))
                minuses = tuple(dict.fromkeys((*card.minuses, "whale_only")))
                card = replace(
                    card,
                    bearing_verdict="hold",
                    macro_multiplier=Decimal("1"),
                    pluses=pluses,
                    minuses=minuses,
                )
        self.knowledge.put_card_live(symbol, card.to_payload())
        return card

    def _apply_author_pump(
        self, card: CardLive, symbol: str, now: datetime, vol: Any
    ) -> CardLive:
        """Allow-list pump. Hold only when a listed source actually hit."""
        if not self.knowledge.available():
            return card
        try:
            from capitalizator.authors.pump import FetchedItem
            from capitalizator.authors.pump import pump as author_pump
            from capitalizator.authors.sources import load_sources as load_author_book

            book = load_author_book()
        except (ValueError, FileNotFoundError, OSError):
            return card
        if not book.sources:
            return card
        allowed = {row.source_id: row for row in book.sources}
        since = (now - timedelta(hours=48)).isoformat()
        fetched: list[Any] = []
        for item in self.knowledge.intel_items(since=since, limit=200):
            sid = str(item.get("source_id") or "")
            if sid not in allowed:
                continue
            kind = allowed[sid].kind
            url = str(item.get("url") or allowed[sid].url)
            try:
                known = datetime.fromisoformat(str(item["known_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError, TypeError):
                continue
            fetched.append(
                FetchedItem(
                    source_id=sid,
                    kind=kind,
                    url=url,
                    title=str(item.get("text") or ""),
                    body="",
                    known_at=known,
                )
            )
        if not fetched:
            return card
        try:
            pumped = author_pump(symbol=symbol, now=now, book=book, fetched=fetched, volume=vol)
        except ValueError:
            return card
        if pumped is not None and pumped.bearing_verdict == "hold":
            return replace(
                card,
                bearing_verdict="hold",
                macro_multiplier=Decimal("1"),
                pluses=tuple(dict.fromkeys((*card.pluses, *pumped.pluses))),
                minuses=tuple(dict.fromkeys((*card.minuses, *pumped.minuses))),
            )
        return card

    def _apply_author_weights(self, card: CardLive) -> CardLive:
        if not self.knowledge.available():
            return card
        raw = self.knowledge.meta("author_weights")
        if not raw:
            return card
        try:
            weights = json.loads(raw)
        except json.JSONDecodeError:
            return card
        if not isinstance(weights, dict) or not weights:
            return card
        block = weights.get("authors")
        if not isinstance(block, dict):
            block = weights
        n = 0
        hits = 0
        for row in block.values():
            if not isinstance(row, dict):
                continue
            n += int(row.get("n") or 0)
            hits += int(row.get("hits") or 0)
        if n <= 0:
            return card
        return replace(card, jury_b_n=n, jury_b_for=hits)

    def btc_same_side(self, idea_side: str) -> bool:
        """Is this idea on BTC's side? A box is neutral ground for both sides; a trend
        agrees only with ideas in its direction; unknown HTF agrees with nothing."""
        if self.btc.regime == "box":
            return True
        if self.btc.direction == "long":
            return idea_side == "buy"
        if self.btc.direction == "short":
            return idea_side == "sell"
        return False

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
        # The direction behind "trend" (long / short) is what "same side as BTC" needs;
        # a box or unknown HTF has none.
        bias = self.zones_map.htf_bias("BTCUSDT", closed_at, st.bars)
        self.btc.direction = bias if bias in {"long", "short"} else None
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
        # +1R take fraction is decided here, not at submit. A stamped expand
        # on the ticket is the wrong clock (expand_ok needs a live day/book).
        for pos in self.paper.open_for(trade.symbol):
            # The take clock is this print. After +1R the fraction is done —
            # flipping expand later would let score flatten an EXPAND remainder.
            if pos.state == "open" and not pos.half_taken:
                pos.labels["expand"] = self._expand_now(
                    pos, trade.exchange_ts, at_1r_take=True
                )
        changed = self.paper.on_print(trade)
        for pos in changed:
            if pos.half_taken and not pos.labels.get("harvest_noted"):
                pos.labels["harvest_noted"] = True
                if self.policy.window(trade.exchange_ts).name == "overlap":
                    self._note_hyexec("harvest", symbol=pos.symbol, now=trade.exchange_ts)
        # Resting +1R half on the venue as soon as the twin is filled, not after
        # the tape has already printed through +1R (that was a taker / a miss).
        for pos in self.paper.open_for(trade.symbol):
            if (
                pos.source == "demo"
                and pos.state == "open"
                and pos.entry_px is not None
                and pos.paper_id not in self._half_sent
                and not pos.labels.get("half_sent")
            ):
                self._half_sent.add(pos.paper_id)
                pos.labels["half_sent"] = True  # persisted with the twin: no re-send after restart
                venue_qty = self._venue_qty(pos.symbol)
                base = venue_qty if venue_qty is not None and venue_qty > 0 else pos.qty
                half_px = (
                    pos.entry_px + pos.r_px if pos.side == "buy" else pos.entry_px - pos.r_px
                )
                expand = self._expand_now(pos, trade.exchange_ts, at_1r_take=True)
                pos.labels["expand"] = expand
                self._oms(
                    pos, "half_tp", trade.exchange_ts,
                    qty=str(base * take_at_1r(expand=expand)),
                    price=str(half_px),
                    reason="+1R half",
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
        opened = self._drop_resolved_touches(opened)
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
        self._sync_window_halt(when)
        self._sync_hour_start(when)
        self.paper.on_clock(when)
        out: list[dict[str, Any]] = []
        if self.knowledge.available():
            self._refresh_hyexec_model_go()
            # Gateway watchdog: process liveness, not tape time. Catch-up ticks
            # used exchange_ts here and the signer blocked `desk` for a live box.
            self._ui_put("desk_heartbeat", datetime.now(tz=UTC).isoformat())
            if force_flush:
                # Always written on a clock tick: a symbol that gained facts leaves the banner.
                self._ui_put("refused_symbols", json.dumps(self.refused_symbols, sort_keys=True))
            if force_flush:
                out.extend(self._consume_commands(when))
                self._reload_risk_config()
                self._reload_instruments()
                self._refresh_calibration(when)
                self._refresh_correlation(when)
                self._apply_hyexec_score_exit(when)
                out.extend(self._sync_exchange_state(when))
                out.extend(self._retire_zones(when))
            if force_flush:
                # Twins and venue proof survive a restart (audit B3); once per clock tick,
                # not per print (audit E).
                self._ui_put("paper_open", json.dumps(self.paper.snapshot(), sort_keys=True))
                self._ui_put("venue_seen", json.dumps(sorted(self._venue_seen)))
                self._ui_put("sl_ack", json.dumps(self._sl_ack, sort_keys=True))
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

    ZONE_RETIRE_EVERY_S = 60.0

    def _retire_invalidated(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        """Own-TF close through the band takes the level off the map."""
        if st.symbol != bar.symbol:
            return []
        closed_at = bar.close_ts + timedelta(microseconds=1)
        gone = self.registry.invalidate_broken(now=closed_at, bars=(bar,))
        if not gone:
            return []
        for zone in gone:
            if self.knowledge.available():
                self.knowledge.drop_zone(zone.zone_id)
            self.zone_cache.pop(zone.symbol, None)
            self._persisted_zone_ids.pop(zone.symbol, None)
        return [
            {"event": "zone_invalidated", "zone_id": z.zone_id, "symbol": z.symbol,
             "tf": z.tf, "method": z.method}
            for z in gone
        ]

    def _retire_zones(self, now: datetime) -> list[dict[str, Any]]:
        """PHASE-BUILD `die_no_touch_h`: zones nobody trades and the engine no longer
        draws leave the map (memory, persisted table, per-symbol cache). Once a minute."""
        last = self._last_zone_retire
        if last is not None and (now - last).total_seconds() < self.ZONE_RETIRE_EVERY_S:
            return []
        self._last_zone_retire = now
        gone = self.registry.retire_zones(now=now)
        if not gone:
            return []
        for zone in gone:
            if self.knowledge.available():
                self.knowledge.drop_zone(zone.zone_id)
            self.zone_cache.pop(zone.symbol, None)
            self._persisted_zone_ids.pop(zone.symbol, None)
        return [
            {"event": "zone_retired", "zone_id": z.zone_id, "symbol": z.symbol, "tf": z.tf,
             "method": z.method}
            for z in gone
        ]

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
        """Resolved touches as Forecast samples. Journal first, then unsaved rows.
        The journal part is cached and rebuilt only when the journal grew (audit E:
        a full journal scan on every jury)."""
        rows = self.knowledge.journal_rows()
        key = (len(rows), rows[-1].get("touch_id") if rows else None)
        if self._oko_samples_cache is not None and self._oko_samples_cache[0] == key:
            out = list(self._oko_samples_cache[1])
            seen = set(self._oko_samples_cache[2])
            return self._oko_samples_tail(out, seen)
        out: list[OkoSample] = []
        seen: set[str] = set()
        for row in rows:
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
        self._oko_samples_cache = (key, list(out), set(seen))
        return self._oko_samples_tail(out, seen)

    def _queue_ahead(self, symbol: str, side: str, px: Decimal) -> Decimal | None:
        """Resting size at our limit price on our side of the book at submit: the queue in
        front of a paper order. None when the book has no such level (the fill model
        then falls back to "first print at the level")."""
        st = self.symbols.get(symbol)
        if st is None or not st.book.ready:
            return None
        levels = st.book.levels("bid" if side == "buy" else "ask")
        size = levels.get(px)
        return Decimal(str(size)) if size is not None else None

    def _oko_samples_tail(self, out: list[OkoSample], seen: set[str]) -> list[OkoSample]:
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
        touch = self._bind_last_touch(st)
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
        # A crossed/locked book is not a quote — do not feed it to the Passport.
        probe = st.book_pre or st.book
        if validate(probe).ok:
            self._oko_observe(st, touch, now)
        touch = self._bind_last_touch(st)
        if touch is None:
            return []
        book = st.book_pre or st.book
        bid, ask = book.best() if book.ready else (None, None)
        mid = ((bid + ask) / 2) if bid is not None and ask is not None else touch.trade_px
        hit_side = "bid" if zone.side == "support" else "ask"
        opp_best = ask if hit_side == "bid" else bid
        if opp_best is None:
            opp_best = touch.trade_px
        t_end = touch.ts + timedelta(seconds=self.config.zlg_window_s)
        prints = [
            (
                require_utc(t.exchange_ts),
                Decimal(str(t.payload["px"])),
                Decimal(str(t.payload.get("qty") or "0")),
            )
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
        if self._bind_last_touch(st) is None:
            return
        touch = st.last_touch
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
        intel_cal = (
            calendar_from_intel(self.knowledge, now=now) if self.knowledge.available() else ()
        )
        if not self.calendar and not intel_cal:
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

    def _bind_last_touch(self, st: SymbolState) -> Touch | None:
        """Registry row for the armed touch, or clear a stale pointer.

        `_drop_resolved_touches` and journal replay can remove a touch_id while
        `SymbolState.last_touch` still points at it. fill_cav then KeyError'd and
        killed the process (crash loop on every bar close).
        """
        touch = st.last_touch
        if touch is None:
            return None
        live = next((t for t in self.registry.touches if t.touch_id == touch.touch_id), None)
        if live is None:
            st.last_touch = None
            st.state = "IDLE"
            st.zlg_card = None
            return None
        st.last_touch = live
        return live

    def _eval_cav_and_jury(self, st: SymbolState, bar: Bar) -> list[dict[str, Any]]:
        touch = self._bind_last_touch(st)
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
        if bar.tf == zone.tf:
            cav = cav_label(zone, bar, t=closed_at, htf_bias=htf, closed_bars=st.bars)
        else:
            cav = confirm_label(
                zone,
                bar,
                t=closed_at,
                htf_bias=htf,
                closed_bars=st.bars,
                ladder=self.config.structure_tfs,
            )
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
        # 2.9.3: long vs BTC support break; short vs BTC resistance break — the same
        # law BtcVeto applies inside `propose`, evaluated here for the jury voice.
        break_against = False
        if st.symbol != "BTCUSDT":
            break_against = (
                self.btc.broke_support
                and not self.btc_veto.allow(
                    alt_side=idea_side, btc_broke=True, btc_zone_side="support"  # type: ignore[arg-type]
                )
            ) or (
                self.btc.broke_resistance
                and not self.btc_veto.allow(
                    alt_side=idea_side, btc_broke=True, btc_zone_side="resistance"  # type: ignore[arg-type]
                )
            )
        btc_same_side = self.btc_same_side(idea_side)
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
            cav_tf=bar.tf,
            btc_break_against=break_against,
            btc_state=row.btc_regime,
            session_name=self.policy.clock_name(row.ts),
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
                "session_name": row.session_name or self.policy.clock_name(row.ts),
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
                "book_plus": _book_plus(st.book, idea_side),
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
        journal.update(_feature_journal(st.last_features))
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
            "btc_direction": self.btc.direction,
            "btc_same_side": btc_same_side,
            # Zone facts travel with the touch: reports and the UI must not depend on the
            # zone still being on the map (zones retire after die_no_touch_h).
            "zone_lo": str(zone.lo),
            "zone_hi": str(zone.hi),
            "zone_tf": zone.tf,
            "confirm_tf": vote_tf(zone.tf, self.config.structure_tfs),
            "zone_method": zone.method,
            "zone_created_as_of": zone.created_as_of.isoformat(),
            "wick_extreme": str(wick_extreme),
            "fade_side": fade_side,
            "fade_tag": "fade_spring" if fade_side else None,
            "b_gate": b_gate,
            "b_marks_red": marks_red,
            "has_tvh": has_tvh,
            "shadow_would_no_marks": shadow_would_no_marks,
            "shadow_would_marks": shadow_would_marks,
            "decision_ms": (closed_at - touch.ts).total_seconds() * 1000.0,
            "paper_gates": paper_gates_snapshot(n_zlg=n_zlg, gesture=row.gesture),
            "liquidity": self._liquidity_stamped.get(row.touch_id) or self._liquidity_of(st, row),
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
        # Session policy verdict is journalled for every touch, sent or not, so the
        # per-window statistics can compare "would send" with "did send".
        session_verdict = self.policy.decide(
            closed_at,
            self.calendar,
            idea=idea,
            symbol=st.symbol,
            next_funding_at=self.next_funding.get(st.symbol),
            rank=self.universe_rank(),
            screened=self.screened_symbols(closed_at),
        )
        window: WindowState = session_verdict.state
        payload_row["session_window"] = window.name
        payload_row["session_weekend"] = window.weekend
        payload_row["session_gate"] = session_verdict.reason
        payload_row["session_size_mult"] = str(window.size_mult)
        payload_row["session_k_atr"] = str(window.k_atr)
        self._sentiment_multiplier(closed_at)
        frag = self._fragility(st)
        if card is not None and "whale_only" in card.minuses:
            whales = "whale_only"
        elif frag.get("forbid_long") or frag.get("forbid_short"):
            whales = "fragile"
        else:
            whales = "ok"
        trace = DecisionTrace(
            touch_id=row.touch_id,
            symbol=st.symbol,
            closed_at=closed_at.isoformat(),
            contour_a=str(jury),
            contour_b=b_gate or (card.bearing_verdict if card is not None else "none"),
            contour_c=str(payload_row.get("challenger_tag") or "silent"),
            intel=intel_atom(card.pluses, card.minuses) if card is not None else None,
            sentiment=self._sentiment_reason,
            whales=whales,
            skip_reason=skip,
            decision_ms=float(extra["decision_ms"]),
        )
        payload_row["decision_trace"] = trace.to_payload()
        if self.knowledge.available():
            self.knowledge.set_meta(
                "decision_trace", json.dumps(trace.to_payload(), sort_keys=True)
            )
        self.knowledge.put_journal_touch(row.touch_id, payload_row)
        self._publish_decision_latency()
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
        vah, val = self._value_area(card)
        if shadow_would:
            pid = self._submit_paper(
                row, zone, known_zones, idea=idea, side=idea_side, wick_extreme=wick_extreme,
                now=closed_at, source="shadow", tag=idea_shadow_tag(idea),
                vah=vah, val=val,
            )
            if pid:
                paper_ids["shadow"] = pid
        if fade_side is not None and has_tvh:
            pid = self._submit_paper(
                row, zone, known_zones, idea="fade_spring", side=fade_side,
                wick_extreme=wick_extreme, now=closed_at, source="fade", tag="fade_spring",
                vah=vah, val=val,
            )
            if pid:
                paper_ids["fade"] = pid
        # Contour C challenger: the same idea WITHOUT the jury's accord (TVH only, no
        # VETO). It never leaves paper; it exists so the exam and the class calibration
        # see every class the champion refuses, not only the ones it takes.
        if has_tvh and not shadow_would and jury != "VETO" and b_gate is None:
            pid = self._submit_paper(
                row, zone, known_zones, idea=idea, side=idea_side, wick_extreme=wick_extreme,
                now=closed_at, source="challenger", tag=idea_shadow_tag(idea),
                vah=vah, val=val,
            )
            if pid:
                paper_ids["challenger"] = pid
        if paper_ids:
            payload_row["paper_ids"] = paper_ids
            self.knowledge.put_journal_touch(row.touch_id, payload_row)
        sent = False
        if (
            self.allow_hyexec_send(book_ticket=shadow_would, symbol=st.symbol)
            and skip is None
            and self.user_mode in {"demo", "live"}
            and self.hello_ok()
            and book.ready
            and session_verdict.allow
        ):
            book_check = validate(book)
            if not book_check.ok:
                payload_row["send_skip"] = f"book:{book_check.reason}"
                self.knowledge.put_journal_touch(row.touch_id, payload_row)
            spr = book.spread()
            bid, ask = book.best()
            mid_px = (bid + ask) / 2 if bid is not None and ask is not None else None
            if book_check.ok and spr is not None and mid_px is not None and mid_px > 0:
                fragility = self._fragility(st)
                payload_row["fragility"] = fragility
                typical_move, tm_source = self._typical_move(st, row.trade_px)
                payload_row["typical_move"] = None if typical_move is None else str(typical_move)
                payload_row["typical_move_source"] = tm_source
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
                    # Measured, not the dataclass default: ATR14/price, else this bar's range.
                    typical_move=typical_move,
                    # The closed bar's liquidity label; a dead bar is not a market to enter.
                    volume_ok=row.bar_quality != "illiquid",
                    lev=self.risk_config.max_lev,
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
                    k_atr=self.k_atr_for(window, st.symbol),
                    max_stop_atr=self.risk_config.max_stop_atr,
                    max_stop_pct=self.risk_config.max_stop_pct,
                    manual_stop_frac=self.risk_config.manual_stop_frac,
                    liq_levels=self.liquidation_levels(st, closed_at),
                    vah=self._value_area(card)[0],
                    val=self._value_area(card)[1],
                    next_funding_at=self.next_funding.get(st.symbol),
                    universe_rank=self.universe_rank(),
                    screened=self.screened_symbols(closed_at),
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
                    # Window, card macro and monthly sentiment: the smallest wins.
                    macro_multiplier=min(
                        Decimal("1") if card is None else card.macro_multiplier,
                        self.window_size_mult(window),
                        self._sentiment_multiplier(closed_at),
                    ),
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
                self.strategy.budget = self.account.budget(
                    closed_at, key=window.budget_key, max_n=window.budget
                )
                intent = self.strategy.propose(snap)
                payload_row["would_aplus"] = bool(getattr(self.strategy, "last_aplus", False))
                if intent is None:
                    # The strategy's own refusal is a journal fact, like every gate after it.
                    payload_row["send_skip"] = (
                        f"propose:{getattr(self.strategy, 'last_skip', None) or 'refused'}"
                    )
                    self.knowledge.put_journal_touch(row.touch_id, payload_row)
                else:
                    trade_labels = self._trade_labels(
                        row, zone, window=window, atr=snap.atr, spread=spr,
                        liq_levels=snap.liq_levels, stop=intent.stop, now=closed_at,
                    )
                    sized, gate_info = self._size_and_gate(
                        intent, st.symbol, closed_at, labels=trade_labels,
                    )
                    payload_row.update(gate_info)
                    self.knowledge.put_journal_touch(row.touch_id, payload_row)
                    if sized is not None:
                        if gate_info.get("desk_step") == "aplus":
                            self._note_hyexec("aplus", symbol=st.symbol, now=closed_at)
                        intent_id = self.knowledge.enqueue_intent(
                            sized.model_dump(mode="json"),
                            created_ts=row.ts.isoformat(),
                        )
                        # Budget is spent here, on an intent that passed every gate.
                        self.account.budget(
                            closed_at, key=window.budget_key, max_n=window.budget
                        ).on_intent()
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
                            queue_ahead=self._queue_ahead(st.symbol, sized.side, sized.entry),
                            funding_interval_min=self._instrument_for(st.symbol).funding_interval_min,
                            structural=sized.structural,
                            stop_components=dict(sized.stop_components or {}),
                            labels=trade_labels,
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
    DESK_COMMANDS = (
        "flatten",
        "release_halts",
        "pause_entries",
        "resume_entries",
        "promote",
        "drift_release",
        "add_in_profit",
    )
    # Bounded in-memory tails for a 24/7 process (audit §5): the journal in SQLite is
    # the record; these are working windows.
    SHADOW_WRITES_MAX = 2000
    WIDTH_HISTORY_MAX = 5000

    def _run_command(
        self, kind: str, payload: Mapping[str, Any], symbol: Any, now: datetime
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Execute one operator command. Returns (result, events)."""
        if kind == "flatten":
            known = set(self.symbols) | set(self.account.open) | set(self.paper.open_symbols())
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
            return {"targets": targets, "events": len(events)}, events
        if kind == "release_halts":
            assert self.account.halts is not None
            self.account.halts.release(ack=True)
            self.account.persist()
            return {"released": True}, [{"event": "release_halts"}]
        if kind == "pause_entries":
            self.entries_paused = True
            self.knowledge.set_meta("entries_paused", "1")
            return {"paused": True}, [{"event": "pause_entries"}]
        if kind == "resume_entries":
            self.entries_paused = False
            self.knowledge.set_meta("entries_paused", "0")
            return {"paused": False}, [{"event": "resume_entries"}]
        if kind == "drift_release":
            window = None if symbol in {None, "", "ALL"} else str(symbol)
            cleared = self.release_drift(window)
            return {"windows": cleared}, [{"event": "drift_release", "windows": cleared}]
        if kind == "add_in_profit":
            return self._add_in_profit_command(payload, symbol, now)
        # promote — run the exam now; flip the label only on a pass
        result = self._promote(payload, now)
        return result, [{"event": "promote", **{k: result[k] for k in ("passed",)}}]

    def _add_in_profit_command(
        self, payload: Mapping[str, Any], symbol: Any, now: datetime
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Validate a second leg above (long) / below (short) entry. No venue add exists."""
        reject_forbidden_keys(dict(payload))
        if symbol in {None, "", "ALL"}:
            raise ValueError("add_in_profit needs a symbol")
        idea = self.account.open.get(str(symbol))
        if idea is None:
            raise ValueError("no open idea")
        if "add_price" not in payload:
            raise ValueError("add_price required")
        add_price = Decimal(str(payload["add_price"]))
        extra = Decimal(str(payload.get("extra_risk") or "0.005"))
        equity = self.account.sizing_equity()
        if equity <= 0:
            raise ValueError("equity must be > 0")
        open_risk = idea.qty * abs(idea.entry - idea.stop) / equity
        got = self.manager.add_in_profit(
            side=idea.side,  # type: ignore[arg-type]
            entry=idea.entry,
            add_price=add_price,
            extra_risk=extra,
            open_risk=open_risk,
        )
        week_start = self.account.halts.week_start
        if week_start <= 0:
            raise ValueError("week_start must be > 0")
        week_pnl = (self.account.equity - week_start) / week_start
        if not pyramid_ok(week_pnl=week_pnl):
            raise ValueError("behind week pace")
        self._note_hyexec("pyramid", symbol=str(idea.symbol), now=now)
        row = {
            "action": got.action,
            "symbol": idea.symbol,
            "side": got.side,
            "entry": str(got.entry),
            "add_price": str(got.add_price),
            "extra_risk": str(got.extra_risk),
            "open_risk": str(got.open_risk),
            "total_risk": str(got.total_risk),
            "at": now.isoformat(),
            "venue": False,
        }
        twins = [p for p in self.paper.open_for(idea.symbol) if p.state == "open"]
        touch_id = twins[0].touch_id if twins else f"add_in_profit:{idea.symbol}"
        existing = self.knowledge.get_journal_touch(touch_id) or {"touch_id": touch_id}
        existing["add_in_profit"] = row
        self.knowledge.put_journal_touch(touch_id, existing)
        return row, [{"event": "add_in_profit", **row}]

    def _consume_commands(self, now: datetime) -> list[dict[str, Any]]:
        """Operator commands are claimed atomically from the one `desk_commands` table
        (no read-modify-write on meta): a command posted between two desk ticks can
        neither be lost nor run twice; its result is written back for the console."""
        out: list[dict[str, Any]] = []
        for cmd in self.knowledge.claim_commands(self.DESK_COMMANDS):
            kind = cmd["kind"]
            payload = cmd["payload"]
            symbol = payload.get("symbol")
            try:
                result, events = self._run_command(kind, payload, symbol, now)
                out.extend(events)
                self.knowledge.mark_command(cmd["id"], "done", result)
            except Exception as exc:  # one bad command must not stop the others
                self.knowledge.mark_command(cmd["id"], "failed", {"error": str(exc)})
                out.append({"event": "command_failed", "kind": kind, "error": str(exc)})
        return out

    def _promote(self, payload: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """Operator asked for the exam. The report is recorded (meta `exam_last`); a pass
        records the winner as `champion_candidate`. The actual switch of what the desk
        sends is a code-reviewed change (the challenger reading becomes the sendable
        idea) — never an automatic flip in the fight (ARCHITECTURE-AZ §6.1 п.6)."""
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
            self.knowledge.set_meta("champion_candidate", json.dumps(champion, sort_keys=True))
        return body

    # --- exchange truth → account (live/demo) --------------------------------------
    EXCHANGE_STATE_MAX_AGE_S = 300.0
    VENUE_FLAT_GRACE_S = 90.0

    def _sync_exchange_state(self, now: datetime) -> list[dict[str, Any]]:
        """In demo/live the signer publishes wallet equity and venue positions (REST truth).

        * equity → Account.set_equity (sizing and halts run on real equity, not paper);
        * an intent the venue refused (`failed`) frees its open idea at once;
        * a filled twin whose venue position is gone (stop/TP/liquidation on the venue)
          is closed here so the account, the one-position rule and the journal agree;
        * a venue position without a confirmed Mark SL: one OMS `amend_stop`, then
          flatten on the next reconcile snapshot (signer still never exits itself).
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
                prev_src = self.account.equity_source
                self.account.set_equity(eq, source=f"exchange:{self.user_mode}", now=now)
                self._sync_window_halt(now, rebase=not prev_src.startswith("exchange"))
                self._sync_hour_start(now)
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
        out.extend(self._handle_stop_missing(state, state_at, now))
        return out

    def _demo_twins_for_sl(self, symbol: str) -> list[PaperPosition]:
        """Our live idea on this symbol: a demo twin that still carries a stop.

        Pending (unfilled on paper) still counts — `stop_missing` means the venue
        already has size; the twin holds the stop we asked the gateway to attach.
        Shadow / fade never went to the venue.
        """
        return [
            p
            for p in self.paper.open_for(symbol, source="demo")
            if p.stop is not None and p.stop > 0 and p.state in {"open", "pending"}
        ]

    def _handle_stop_missing(
        self, state: Mapping[str, Any], state_at: datetime, now: datetime
    ) -> list[dict[str, Any]]:
        """Venue position without a confirmed Mark SL: retry once, then flatten.

        First reconcile snapshot → OMS `amend_stop` (twin.stop). A later snapshot
        that still lists the symbol → OMS `flatten` + paper flatten. Same snapshot
        must not retry or flatten (desk ticks faster than `reconcile_s`). Unknown
        venue positions (no demo twin) stay with the operator / signer block.
        """
        missing = {str(s) for s in (state.get("stop_missing") or []) if s}
        out: list[dict[str, Any]] = []
        for symbol in list(self._sl_ack):
            if symbol not in missing:
                del self._sl_ack[symbol]
        if not missing:
            return out
        for symbol in sorted(missing):
            twins = self._demo_twins_for_sl(symbol)
            if not twins:
                self._sl_ack.pop(symbol, None)
                continue
            rec = self._sl_ack.get(symbol)
            if rec is None:
                rec = {"since": state_at.isoformat(), "amended": False, "flattened": False}
                self._sl_ack[symbol] = rec
            if rec.get("flattened"):
                continue
            twin = twins[0]
            if not rec.get("amended"):
                self._oms(
                    twin, "amend_stop", now, stop=str(twin.stop), reason="sl_retry"
                )
                rec["amended"] = True
                rec["since"] = state_at.isoformat()
                rec["touch_id"] = twin.touch_id
                rec["stop"] = str(twin.stop)
                rec["attempts"] = 1
                self._note_sl_ack(
                    twin, now, event="sl_retry", stop=str(twin.stop), attempts=1
                )
                out.append(
                    {
                        "event": "sl_retry",
                        "symbol": symbol,
                        "stop": str(twin.stop),
                        "touch_id": twin.touch_id,
                    }
                )
                continue
            try:
                since = datetime.fromisoformat(str(rec["since"]).replace("Z", "+00:00"))
            except (KeyError, ValueError, TypeError):
                since = state_at
            if state_at <= since:
                continue
            self._oms(twin, "flatten", now, reason="sl_unconfirmed")
            px = self.last_price.get(symbol, twin.entry_px or twin.limit_px)
            self.paper.flatten(symbol, px, now, reason="sl_unconfirmed")
            rec["flattened"] = True
            rec["attempts"] = int(rec.get("attempts") or 1) + 1
            rec["flattened_at"] = now.isoformat()
            attempts = int(rec["attempts"])
            self._note_sl_ack(
                twin,
                now,
                event="sl_unconfirmed",
                stop=str(twin.stop),
                attempts=attempts,
            )
            out.append(
                {
                    "event": "sl_unconfirmed",
                    "symbol": symbol,
                    "attempts": attempts,
                    "touch_id": twin.touch_id,
                }
            )
        return out

    def _note_sl_ack(
        self,
        twin: PaperPosition,
        now: datetime,
        *,
        event: str,
        stop: str,
        attempts: int,
    ) -> None:
        """Journal + meta so Chronos and the banner see retry / forced flatten."""
        if not self.knowledge.available():
            return
        body = {
            "event": event,
            "at": now.isoformat(),
            "symbol": twin.symbol,
            "touch_id": twin.touch_id,
            "stop": stop,
            "attempts": attempts,
        }
        self.knowledge.set_meta("sl_ack_last", json.dumps(body, sort_keys=True))
        if event == "sl_unconfirmed":
            self.knowledge.set_meta("sl_unconfirmed", json.dumps(body, sort_keys=True))
        row = self.knowledge.get_journal_touch(twin.touch_id)
        if row is None:
            return
        row["sl_ack"] = body
        self.knowledge.put_journal_touch(twin.touch_id, row)

    CALIBRATION_REFRESH_S = 600.0

    # Break-even winrate of a 2R target at the worst cost the EV gate admits
    # (costs = R / fee_multiple_min = R/5): p = (R + R/5) / 3R = 0.4. Used only to flag
    # closed windows whose paper record clears it; the per-trade gate uses its own p.
    BREAKEVEN_2R_MAKER = Decimal("0.4")

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
        # Stop buffer per window from the MAE of winning paper trades (widen only).
        self._k_atr_calibrated = k_atr_by_window(rows)
        # Expected hold per idea×window for the EV gate's funding term.
        self._hold_hours = median_hold_hours(rows)
        # Page-Hinkley on each window's loss series: a window whose loss rate rose is
        # cut to half size until the operator releases it (drift_release command).
        # A release records the series length; detection then runs only on trades
        # closed after it, so the same old losses cannot re-flag the window at once.
        changed = False
        for window, bits in loss_series_by_window(rows).items():
            if window in self._window_drift:
                continue
            fresh = bits[self._drift_ack_n.get(window, 0) :]
            if len(fresh) < self.DRIFT_MIN_N:
                continue
            if self._drift.run(fresh).drift:
                self._window_drift[window] = now.isoformat()
                changed = True
        if changed:
            self._persist_drift()
        if self._calibration:
            self._ui_put("calibration", to_meta(self._calibration))
        if self._k_atr_calibrated:
            self._ui_put(
                "k_atr_calibrated",
                json.dumps({k: str(v) for k, v in sorted(self._k_atr_calibrated.items())}),
            )
        # Windows the operator keeps closed but whose paper lower bound clears the
        # break-even of a 2R bounce after maker fees: flagged, never opened here.
        closed = [
            w.name
            for w in self.policy.windows
            if not w.ideas or w.budget <= 0 or w.size_mult <= 0
        ]
        if self.policy.weekend.budget <= 0 or not self.policy.weekend.ideas:
            closed.append(self.policy.weekend.name)
        flagged = eligible_windows(
            self._calibration, breakeven=self.BREAKEVEN_2R_MAKER, closed_windows=closed
        )
        self._ui_put("eligible_windows", json.dumps(flagged, sort_keys=True))
        self._refresh_drift(rows, now)

    # --- drift (4.19.2 / contour C): Page-Hinkley on the champion's error series --------
    DRIFT_WINDOW = 200
    CHAMPION_DRIFT_MIN_N = 40

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
        if len(errors) < self.CHAMPION_DRIFT_MIN_N:
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

    # --- sentiment (2.12.5): monthly extreme greed de-risks; nothing else ----------------
    SENTIMENT_REFRESH_S = 600.0

    def _sentiment_multiplier(self, now: datetime) -> Decimal:
        """×`RiskConfig.sentiment_mult` when the 30-day mean Fear & Greed (intel `fng`
        items) is ≥ `RiskConfig.sentiment_greed`. Hourly readings never decide anything
        ("buy fear" is refused by design)."""
        if (
            self._sentiment_at is not None
            and (now - self._sentiment_at).total_seconds() < self.SENTIMENT_REFRESH_S
        ):
            return self._sentiment_mult
        self._sentiment_at = now
        self._sentiment_mult = Decimal("1")
        self._sentiment_reason = "sentiment_ok"
        if not self.knowledge.available():
            return self._sentiment_mult
        since = (now - timedelta(days=30)).isoformat()
        values: list[float] = []
        for item in self.knowledge.intel_items(kind="fng", since=since, limit=100):
            try:
                values.append(float(item.get("value")))
            except (TypeError, ValueError):
                continue
        # a month is ≥ 20 daily prints; fewer is not a monthly window
        monthly = len(values) >= 20
        extreme = monthly and sum(values) / len(values) >= self.risk_config.sentiment_greed
        verdict = sentiment_decide(window="month" if monthly else "hour", extreme_greed=extreme)
        self._sentiment_reason = verdict.reason
        if verdict.reason == "monthly_greed":
            self._sentiment_mult = self.risk_config.sentiment_mult
        return self._sentiment_mult

    def _hyexec_serve_body(self) -> dict[str, Any] | None:
        if not self.knowledge.available():
            return None
        raw = self.knowledge.meta("hyexec_serve")
        if raw in {None, ""}:
            return None
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return body if isinstance(body, dict) else None

    def _refresh_hyexec_model_go(self) -> None:
        """Serve writes the score. Desk never loads xgboost."""
        body = self._hyexec_serve_body()
        if body is None:
            return
        go = body.get("model_go")
        self.hyexec_model_go = None if go is None else bool(go)

    def _hyexec_go_for(self, symbol: str) -> bool | None:
        body = self._hyexec_serve_body()
        if body is not None:
            by_sym = body.get("by_symbol")
            if symbol and isinstance(by_sym, dict) and symbol in by_sym:
                row = by_sym[symbol]
                if isinstance(row, dict):
                    go = row.get("model_go")
                    return None if go is None else bool(go)
            if symbol and isinstance(by_sym, dict) and by_sym and symbol not in by_sym:
                return None
            if "model_go" in body:
                go = body.get("model_go")
                if go is not None:
                    return bool(go)
                if not by_sym:
                    return None
        return self.hyexec_model_go

    def _hyexec_score_for(self, symbol: str) -> Decimal | None:
        body = self._hyexec_serve_body()
        if body is None:
            return None
        by_sym = body.get("by_symbol")
        if symbol and isinstance(by_sym, dict) and symbol in by_sym:
            row = by_sym[symbol]
            if isinstance(row, dict) and row.get("score") not in {None, ""}:
                try:
                    return Decimal(str(row["score"]))
                except ArithmeticError:
                    return None
        if symbol and isinstance(by_sym, dict) and by_sym:
            return None
        if body.get("score") not in {None, ""}:
            try:
                return Decimal(str(body["score"]))
            except ArithmeticError:
                return None
        return None

    def _apply_hyexec_score_exit(self, now: datetime) -> None:
        """Flatten a FLOOR remainder when the served score dropped. EXPAND holds."""
        for pos in list(self.paper.positions.values()):
            if pos.state != "open" or not pos.half_taken:
                continue
            raw = pos.labels.get("score_entry")
            if raw in {None, ""}:
                continue
            try:
                score_entry = Decimal(str(raw))
            except ArithmeticError:
                continue
            score_now = self._hyexec_score_for(pos.symbol)
            if score_now is None:
                continue
            px = self.last_price.get(pos.symbol)
            if px is None:
                px = pos.entry_px
            if px is None:
                continue
            self.paper.note_score(
                pos.paper_id,
                now=now,
                px=px,
                score_now=score_now,
                score_entry=score_entry,
                drop=SCORE_DROP,
                structure_ok=self._structure_ok_for(pos),
            )

    def allow_hyexec_send(self, *, book_ticket: bool, symbol: str = "") -> bool:
        return may_send(book_ticket=book_ticket, model_go=self._hyexec_go_for(symbol))

    def effective_target_risk(self, *, step: str = "std", window: str = "") -> Decimal:
        base = target_after_drift(drift=self.drift_active, base=self.risk_config.target_risk_pct)
        risk = effective_risk(
            step=step,
            phase_target=self.risk_config.target_risk_pct,
            base_risk=base,
            day_pnl=self.window_halt.day_pnl(),
            window=window or "none",
        )
        return after_hour_dd(hour_dd=self._hour_dd(), risk=risk)

    def _hour_dd(self) -> Decimal:
        start = self._hour_start_equity
        if start <= 0:
            return Decimal("0")
        return (self.account.equity - start) / start

    def _load_hour_start(self) -> None:
        if not self.knowledge.available():
            return
        raw = self.knowledge.meta("hyexec_hour_start")
        if not raw:
            return
        try:
            data = json.loads(raw)
            at = datetime.fromisoformat(str(data["at"]))
            equity = Decimal(str(data["equity"]))
        except (KeyError, TypeError, ValueError, ArithmeticError, json.JSONDecodeError):
            return
        if equity <= 0:
            return
        self._hour_start_at = at
        self._hour_start_equity = equity

    def _sync_hour_start(self, now: datetime) -> None:
        hour = require_utc(now).replace(minute=0, second=0, microsecond=0)
        if self._hour_start_at is None or hour > self._hour_start_at:
            self._hour_start_at = hour
            self._hour_start_equity = self.account.equity
            if self.knowledge.available():
                self.knowledge.set_meta(
                    "hyexec_hour_start",
                    json.dumps(
                        {"at": hour.isoformat(), "equity": str(self._hour_start_equity)},
                        sort_keys=True,
                    ),
                )

    @staticmethod
    def _value_area(card: CardLive | None) -> tuple[Decimal | None, Decimal | None]:
        if card is None:
            return None, None
        return _opt_px(card.volume.vah), _opt_px(card.volume.val)

    def _book_plus_for(self, pos: PaperPosition) -> bool:
        st = self.symbols.get(pos.symbol)
        if st is None or not st.book.ready:
            return False
        imb = st.book.imbalance(5)
        if imb is None:
            return False
        return imb > 0 if pos.side == "buy" else imb < 0

    def _structure_ok_for(self, pos: PaperPosition) -> bool:
        if pos.side == "buy" and self.btc.broke_support:
            return False
        if pos.side == "sell" and self.btc.broke_resistance:
            return False
        if pos.structural is None:
            return False
        px = self.last_price.get(pos.symbol)
        if px is None:
            px = pos.entry_px or pos.limit_px
        return px > pos.structural if pos.side == "buy" else px < pos.structural

    def _expand_now(
        self, pos: PaperPosition, when: datetime, *, at_1r_take: bool = False
    ) -> bool:
        """FLOOR vs EXPAND at the +1R take. Submit-time stamps are not this clock."""
        if pos.side == "buy" and self.btc.broke_support:
            return False
        if pos.side == "sell" and self.btc.broke_resistance:
            return False
        px = self.last_price.get(pos.symbol)
        in_profit = at_1r_take
        if not in_profit and pos.entry_px is not None and px is not None:
            in_profit = px > pos.entry_px if pos.side == "buy" else px < pos.entry_px
        return expand_ok(
            in_profit=in_profit,
            book_plus=self._book_plus_for(pos),
            structure_ok=self._structure_ok_for(pos),
            window=self.policy.window(when).name,
            day_pnl=self.window_halt.day_pnl(),
        )

    def _sync_window_halt(self, now: datetime, *, rebase: bool = False) -> None:
        assert self.account.halts is not None
        day_start = self.account.halts.day_start
        if rebase or self.window_halt.start != day_start:
            self.window_halt = WindowHalt(start_equity=day_start)
            if self.account.halts.peak > self.window_halt.peak:
                self.window_halt.peak = self.account.halts.peak
        self.window_halt.note_window(self.policy.window(now).name, self.account.equity)

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
        # instruments-info lags Bybit's dynamic settlement frequency; the ticker's
        # live interval wins over the hourly snapshot we just merged.
        for symbol, minutes in self._live_funding_interval.items():
            self.instruments.set_funding_interval(symbol, minutes)
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
        # Correlation guard follows the slot count and threshold of the new config.
        if cfg.max_open_positions > 1:
            guard = self.account.correlation
            if guard is None:
                self.account.correlation = CorrelationGuard.load(
                    threshold=cfg.corr_block_threshold
                )
                self._correlation_at = None  # refresh ρ on the next tick
            elif guard.threshold != cfg.corr_block_threshold:
                guard.threshold = cfg.corr_block_threshold
        else:
            self.account.correlation = None
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
        vah: Decimal | None = None,
        val: Decimal | None = None,
    ) -> str | None:
        """Same geometry as the live strategy, sized from the account, no EV gate:
        the shadow measures what the edge is worth *after* costs, it does not filter."""
        inst = self._instrument_for(row_symbol := zone.symbol)
        tick = inst.tick
        away = self.config.bounce_away_ticks
        st = self.state_for(row_symbol)
        window = self.policy.window(now)
        atr = self._atr_for(st)
        liq_levels = self.liquidation_levels(st, now)
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
                atr=atr,
                spread=spread,
                zones=[z for z in known_zones if z.zone_id != zone.zone_id],
                k_atr=self.k_atr_for(window, row_symbol),
                # W3: the shadow measures, it does not filter — no max_stop_atr ceiling
                # here (stop_atr is still recorded in the components for the data);
                # the live path in _eval_cav_and_jury applies the ceiling.
                max_stop_atr=None,
                liq_levels=liq_levels,
                entry=row.trade_px,
                manual_frac=self.risk_config.manual_stop_frac,
                mode=self.risk_config.stop_mode,
                vah=vah,
                val=val,
            )
            stop = smart.stop
            if atr is not None and atr > 0:
                smart.components["stop_atr"] = str(abs(row.trade_px - stop) / atr)
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
            equity=self.account.sizing_equity(),
            entry=row.trade_px,
            stop=stop,
            lev=lev,
            target_risk=self.effective_target_risk(window=window.name),
            deposit_share=cfg.deposit_share_per_trade,
            qty_step=inst.qty_step,
            min_qty=inst.min_qty,
            min_notional=inst.min_notional,
            max_lev=cfg.max_lev,
            side=side,
            day_halt_room=self.account.halts.remaining_frac(self.account.sizing_equity())["day"],
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
            queue_ahead=self._queue_ahead(row_symbol, side, row.trade_px),
            funding_interval_min=inst.funding_interval_min,
            structural=structural,
            stop_components=smart.components,
            labels=self._trade_labels(
                row, zone, window=window, atr=atr, spread=spread, liq_levels=liq_levels,
                stop=stop, now=now,
            ),
        )
        return pid

    def _trade_labels(
        self,
        row: Touch,
        zone: Zone,
        *,
        window: WindowState,
        atr: Decimal | None,
        spread: Decimal | None,
        liq_levels: tuple[Decimal, ...],
        stop: Decimal,
        now: datetime,
    ) -> dict[str, Any]:
        """Per-trade context the per-window statistics need (calibrate.py)."""
        symbol = zone.symbol
        rank = self.universe_rank()
        nxt = self.next_funding.get(symbol)
        liq_dist_atr: str | None = None
        if liq_levels and atr is not None and atr > 0:
            liq_dist_atr = str(min(abs(level - stop) for level in liq_levels) / atr)
        return {
            "cav_label": row.cav_label,
            "zlg_label": row.gesture,
            "symbol": symbol,
            "zone_side": zone.side,
            "btc_regime": row.btc_regime,
            "window": window.name,
            "weekend": window.weekend,
            "symbol_group": self.symbol_group(symbol, rank),
            "size_mult": str(window.size_mult),
            "k_atr": str(self.k_atr_for(window, symbol)),
            "atr": None if atr is None else str(atr),
            "spread_bps": (
                None
                if spread is None or row.trade_px <= 0
                else str((spread / row.trade_px) * Decimal(10_000))
            ),
            "next_funding_in_min": (
                None if nxt is None else str((nxt - require_utc(now)).total_seconds() / 60)
            ),
            "liq_dist_atr": liq_dist_atr,
            "turnover_rank": None if rank is None else rank.get(symbol),
            "zone_tf": zone.tf,
            "cav_tf": row.cav_tf or zone.tf,
            "first_fact_tag": getattr(self.strategy, "last_first_fact_tag", None),
            "aplus": bool(getattr(self.strategy, "last_aplus", False)),
            "score_entry": (
                None
                if (score := self._hyexec_score_for(symbol)) is None
                else str(score)
            ),
        }

    def symbol_group(self, symbol: str, rank: Mapping[str, int] | None) -> str:
        """majors | top10 | rest — the coarse dimension the calibrator aggregates on."""
        if self.policy.is_major(symbol):
            return "majors"
        r = None if rank is None else rank.get(symbol)
        if r is not None and r <= 10:
            return "top10"
        return "rest"

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
                hist = [(datetime.fromisoformat(ts), Decimal(str(lv))) for ts, lv in rows]
            except (json.JSONDecodeError, ValueError, TypeError, ArithmeticError):
                continue
            # Samples from before the openInterest/openInterestValue split were USD
            # figures mixed into a contracts series: drop anything 50× off the median.
            if len(hist) >= 3:
                med = sorted(lv for _t, lv in hist)[len(hist) // 2]
                hist = [(t, lv) for t, lv in hist if med > 0 and lv <= med * 50 and lv * 50 >= med]
            self._oi_hist[symbol] = hist

    def _oi_peak(self, symbol: str) -> bool | None:
        hist = self._oi_hist.get(symbol) or []
        if len(hist) >= self.FUNDING_MIN_N:
            levels = sorted(lv for _ts, lv in hist)
            p95 = levels[min(len(levels) - 1, int(0.95 * (len(levels) - 1)))]
            return hist[-1][1] >= p95
        return self._oi_peak_from_intel(symbol)

    def _oi_peak_from_intel(self, symbol: str) -> bool | None:
        """When the desk OI hist is short, intel bybit_public snapshots are the PIT series."""
        if not self.knowledge.available():
            return None
        levels: list[Decimal] = []
        for item in self.knowledge.intel_items(kind="bybit_public", limit=400):
            if item.get("source_id") != f"bybit_public:{symbol}":
                continue
            raw = item.get("open_interest")
            if raw is None:
                continue
            try:
                levels.append(Decimal(str(raw)))
            except (ValueError, ArithmeticError):
                continue
        if len(levels) < self.FUNDING_MIN_N:
            return None
        ordered = sorted(levels)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]
        return levels[0] >= p95

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
        return z < self.risk_config.fragility_thin_z

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

    def _typical_move(self, st: SymbolState, price: Decimal) -> tuple[Decimal | None, str]:
        """(move, source): the symbol's typical move the spread screener compares costs
        with, as a fraction of price — ATR14 of the working TF once 15 bars exist.
        Before that there is no volatility fact: None (the screen is recorded as
        unmeasured and the EV gate, which prices fees against the trade's actual R,
        decides). Never the dataclass default 1%.
        """
        if price <= 0:
            return None, "no_price"
        atr = self._atr_for(st)
        if atr is not None and atr > 0:
            return atr / price, "atr14"
        return None, "no_atr_yet"

    # --- correlation guard: rolling ρ of HTF close returns, refreshed daily -------------
    CORRELATION_REFRESH_S = 24 * 3600
    CORRELATION_BARS = 180  # 30 days of 4h closes

    def _refresh_correlation(self, now: datetime) -> None:
        guard = self.account.correlation
        if guard is None:
            return
        if (
            self._correlation_at is not None
            and (now - self._correlation_at).total_seconds() < self.CORRELATION_REFRESH_S
        ):
            return
        self._correlation_at = now
        series: dict[str, dict[datetime, Decimal]] = {}
        for symbol, st in self.symbols.items():
            htf = [b for b in st.bars if b.tf == self.config.htf and b.close_ts <= now]
            if len(htf) < 2:
                continue
            closes = [(b.close_ts, b.close) for b in htf[-(self.CORRELATION_BARS + 1) :]]
            series[symbol] = returns_from_closes(closes)
        pairs = guard.refresh(series)
        self._ui_put(
            "correlation",
            json.dumps(
                {"pairs": pairs, "threshold": str(guard.threshold), "at": now.isoformat(),
                 "rho": {"|".join(sorted(k)): str(v.quantize(Decimal("0.001")))
                         for k, v in sorted(guard.rho.items(), key=lambda kv: sorted(kv[0]))}},
                sort_keys=True,
            ),
        )

    # --- session inputs: funding clock, universe rank, day screen, stop inputs ---------
    def _on_funding_payload(self, symbol: str, payload: Mapping[str, Any]) -> None:
        """Ticker funding row → rate, next settlement, live interval, 24h turnover."""
        try:
            self.funding[symbol] = Decimal(str(payload["funding"]))
        except (KeyError, ArithmeticError):
            pass
        nxt = payload.get("next_funding_ts")
        if nxt not in (None, ""):
            try:
                self.next_funding[symbol] = datetime.fromtimestamp(int(nxt) / 1000, tz=UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        interval = payload.get("interval_min")
        if interval not in (None, ""):
            try:
                minutes = int(str(interval))
            except (TypeError, ValueError):
                minutes = 0
            if 0 < minutes <= 24 * 60:
                self._live_funding_interval[symbol] = minutes
                self.instruments.set_funding_interval(symbol, minutes)
        turnover = payload.get("turnover24h")
        if turnover not in (None, ""):
            try:
                value = Decimal(str(turnover))
            except ArithmeticError:
                value = None
            if value is not None and value >= 0:
                self.turnover[symbol] = value

    def universe_rank(self) -> dict[str, int] | None:
        """1 = largest 24h turnover among symbols the desk has seen a ticker for.

        None until at least one turnover is known: the policy then treats every
        non-major as unranked (refused where rank matters) instead of guessing.
        """
        if not self.turnover:
            return None
        ordered = sorted(self.turnover.items(), key=lambda kv: (-kv[1], kv[0]))
        return {symbol: i + 1 for i, (symbol, _) in enumerate(ordered)}

    # Day screen: relative volume of the last closed working bar vs the bars kept in
    # memory (same measure contour B publishes as `rvol`) and OI rising over the kept
    # window (2h, _FEED_KEEP). A symbol is "in play" when both hold.
    SCREEN_RVOL_MIN = Decimal("1.5")

    def screened_symbols(self, now: datetime) -> frozenset[str]:
        # Working bars close on a 15m grid; one scan per minute is exact enough and
        # keeps the per-touch cost independent of the number of symbols.
        minute = require_utc(now).replace(second=0, microsecond=0)
        if self._screen_cache is not None and self._screen_cache[0] == minute:
            return self._screen_cache[1]
        out: set[str] = set()
        for symbol, st in self.symbols.items():
            work = [b for b in st.bars if b.tf == self.config.working_tf and b.close_ts <= now]
            if len(work) < 20:
                continue
            last = work[-1]
            if last.volume is None or last.volume <= 0:
                continue
            prior = [b.volume for b in work[-21:-1] if b.volume is not None and b.volume > 0]
            if len(prior) < 10:
                continue
            mean = sum(prior, Decimal("0")) / len(prior)
            if mean <= 0 or last.volume / mean < self.SCREEN_RVOL_MIN:
                continue
            if len(st.oi) < 2 or st.oi[-1][1] <= st.oi[0][1]:
                continue
            out.add(symbol)
        result = frozenset(out)
        self._screen_cache = (minute, result)
        return result

    DRIFT_MIN_N = 30
    DRIFT_SIZE_MULT = Decimal("0.5")

    def window_size_mult(self, window: WindowState) -> Decimal:
        """Window multiplier, halved while the window's loss series is in drift."""
        if window.name in self._window_drift:
            return window.size_mult * self.DRIFT_SIZE_MULT
        return window.size_mult

    def release_drift(self, window: str | None = None) -> list[str]:
        """Operator command: clear drift flags (all, or one window). Returns what was cleared.

        The current length of each released window's loss series is remembered so the
        detector restarts from the next closed trade, not from the losses already seen.
        """
        cleared = sorted(self._window_drift) if window is None else (
            [window] if window in self._window_drift else []
        )
        if not cleared:
            return []
        series = loss_series_by_window(self.knowledge.paper_trades(source="shadow"))
        for w in cleared:
            del self._window_drift[w]
            self._drift_ack_n[w] = len(series.get(w, []))
        self._persist_drift()
        return cleared

    DRIFT_META = "window_drift_state"

    def _persist_drift(self) -> None:
        state = {"flagged": self._window_drift, "ack_n": self._drift_ack_n}
        body = json.dumps(state, sort_keys=True)
        if self.knowledge.available():
            self.knowledge.set_meta(self.DRIFT_META, body)
        self._ui_put("window_drift", json.dumps(self._window_drift, sort_keys=True))

    def _load_drift(self) -> None:
        raw = self.knowledge.meta(self.DRIFT_META) if self.knowledge.available() else None
        if not raw:
            return
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            return
        flagged = state.get("flagged") if isinstance(state, dict) else None
        ack = state.get("ack_n") if isinstance(state, dict) else None
        if isinstance(flagged, dict):
            self._window_drift = {str(k): str(v) for k, v in flagged.items()}
        if isinstance(ack, dict):
            self._drift_ack_n = {
                str(k): int(v) for k, v in ack.items() if isinstance(v, int) and v >= 0
            }

    def hold_hours_for(self, idea: str, window: WindowState) -> Decimal:
        """Median paper hold of idea×window when n ≥ 30, else the 2h EV default."""
        return self._hold_hours.get(f"{idea}|{window.name}", Decimal("2"))

    def k_atr_for(self, window: WindowState, symbol: str) -> Decimal:
        """Window k_atr, widened (never narrowed) by the MAE calibration of this class."""
        calibrated = self._k_atr_calibrated.get(window.name)
        if calibrated is None:
            return window.k_atr
        return max(window.k_atr, calibrated)

    LIQ_CLUSTER_MIN_ROWS = 20

    def liquidation_levels(self, st: SymbolState, now: datetime) -> tuple[Decimal, ...]:
        """Price levels where liquidations clustered in the kept window (allLiquidation).

        Bucket = one tick·cluster_ticks grid; keep buckets whose USDT volume is at or
        above the 90th percentile once ≥ 20 rows exist. Fewer rows → no levels (not a
        guess). These are stop magnets (retail stops sit where leverage was flushed).
        """
        rows = [r for r in st.liquidations if require_utc(r.exchange_ts) <= now]
        if len(rows) < self.LIQ_CLUSTER_MIN_ROWS:
            return ()
        tick = self.tick_for(st.symbol)
        step = tick * 5
        buckets: dict[Decimal, Decimal] = {}
        for r in rows:
            try:
                px = Decimal(str(r.payload["px"]))
                qty = Decimal(str(r.payload["qty"]))
            except (KeyError, ArithmeticError):
                continue
            if px <= 0 or qty <= 0:
                continue
            key = (px / step).to_integral_value() * step
            buckets[key] = buckets.get(key, Decimal("0")) + px * qty
        if not buckets:
            return ()
        volumes = sorted(buckets.values())
        p90 = volumes[min(len(volumes) - 1, int(0.9 * (len(volumes) - 1)))]
        return tuple(sorted(px for px, vol in buckets.items() if vol >= p90))

    def _drop_resolved_touches(self, opened: list[Touch]) -> list[Touch]:
        """Same touch_id already decided in the journal is not a new arm.

        Replay after a restart recreates the deterministic touch_id. Leaving it
        pending would overwrite the journal and block a live touch of the zone.
        """
        if not opened or not self.knowledge.available():
            return opened
        keep: list[Touch] = []
        drop: set[str] = set()
        for touch in opened:
            row = self.knowledge.get_journal_touch(touch.touch_id)
            if row is not None and row.get("outcome") not in PENDING:
                drop.add(touch.touch_id)
                continue
            keep.append(touch)
        if drop:
            self.registry.touches = [t for t in self.registry.touches if t.touch_id not in drop]
            for st in self.symbols.values():
                if st.last_touch is not None and st.last_touch.touch_id in drop:
                    st.last_touch = None
                    st.state = "IDLE"
                    st.zlg_card = None
        return keep

    def _trail_state(self, pos: PaperPosition) -> TrailState:
        stt = self._trails.get(pos.paper_id)
        if stt is None:
            assert pos.entry_px is not None
            # After a restart the twin carries its trailed stop and its initial stop:
            # 1R must come from the initial one, the phase from the half flag.
            # Construct on the birth stop (always the right side of entry), then
            # apply the current stop — TrailState.__post_init__ rejects a long
            # stop already in profit.
            birth = pos.initial_stop if pos.initial_stop is not None else pos.stop
            stt = TrailState(
                side=pos.side,
                entry=pos.entry_px,
                stop=birth,
                tick=pos.tick,
                initial_stop=pos.initial_stop,
                half_taken=pos.half_taken,
                phase=1 if pos.half_taken else 0,
                exchange_trailing_armed=pos.trailing_distance is not None,
            )
            stt.stop = pos.stop
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
        known_zones = tuple(z for z in self.registry._zones.values() if z.symbol == st.symbol)
        liq = self.liquidation_levels(st, bar.close_ts)
        for pos in list(self.paper.open_for(st.symbol)):
            if pos.state != "open":
                continue
            if self.paper.replay_frozen(pos, bar.close_ts):
                continue
            if (
                self.risk_config.stop_mode in {"hybrid", "manual_bounded"}
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
            for action in self.trail.on_bar(
                stt, work, last_px=last_px, zones=known_zones, liq_levels=liq,
            ):
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
                        pos.paper_id, action.trailing_distance, reason=action.reason,
                        last_px=last_px,
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
                    "tail_cut_r": payload["tail_cut_r"],
                    "half_taken": pos.half_taken,
                    "expand": (
                        None if not pos.half_taken else bool(pos.labels.get("expand"))
                    ),
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
                self._sync_window_halt(when)
            # (3) The twin is the desk's decision; the venue must follow it. flatten on
            # the venue = cancel resting entries + close whatever position is left, so a
            # stop/TP/time/expiry/veto here never leaves an orphan order or position.
            if pos.exit_reason not in {"soft", "b_veto", "sl_unconfirmed"}:
                # those already queued flatten (soft / B veto / missing venue SL)
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
        if symbol not in load_desk_universe().symbols:
            info["send_skip"] = "universe:not_listed"
            return None, info
        ok, why = self.account.allow_entry(symbol)
        if not ok:
            info["send_skip"] = why
            return None, info
        lev = min(cfg.max_lev, inst.max_lev)
        room = self.account.halts.remaining_frac(self.account.sizing_equity())
        window_name = str(labels.get("window") or "")
        step = desk_step(
            first_fact_tag=str(
                labels.get("first_fact_tag")
                or getattr(self.strategy, "last_first_fact_tag", None)
                or "first_fact"
            ),
            size_mult=intent.size_mult,
            aplus=bool(labels.get("aplus") or getattr(self.strategy, "last_aplus", False)),
            window=window_name,
            day_pnl=self.window_halt.day_pnl(),
        )
        decision = size_position(
            equity=self.account.sizing_equity(),
            entry=intent.entry,
            stop=intent.stop,
            lev=lev,
            target_risk=self.effective_target_risk(step=step, window=window_name),
            deposit_share=cfg.deposit_share_per_trade,
            qty_step=inst.qty_step,
            min_qty=inst.min_qty,
            min_notional=inst.min_notional,
            max_lev=cfg.max_lev,
            max_stop_pct=cfg.max_stop_pct,
            side=intent.side,
            day_halt_room=room["day"],
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
            "risk_warning": decision.risk_warning,
            "warning": decision.warning,
            "max_stop_pct": str(cfg.max_stop_pct),
            "day_halt_room": str(room["day"]),
            "equity": str(self.account.equity),
            "sizing_equity": str(self.account.sizing_equity()),
            "participating_share": str(cfg.participating_share),
            "equity_source": self.account.equity_source,
            "config_id": cfg.config_id,
            "desk_step": step,
        }
        if decision.action != "accept":
            info["send_skip"] = f"size:{decision.binding}"
            return None, info
        qty = inst.round_qty(decision.qty * intent.size_mult)
        qok, qwhy = inst.qty_ok(qty, intent.entry)
        if not qok:
            info["send_skip"] = f"size_mult:{qwhy}"
            return None, info
        hold = self._hold_hours.get(f"{intent.tag}|{window_name}", Decimal("2"))
        ev = ev_evaluate(
            qty=qty,
            entry=intent.entry,
            stop=intent.stop,
            tick=inst.tick,
            role="maker",
            funding_rate=self.funding.get(symbol),
            hold_hours=hold,
            funding_interval_min=inst.funding_interval_min,
            fee_multiple_min=cfg.fee_multiple_min,
        )
        info["ev"] = {
            "ok": ev.ok,
            "reason": ev.reason,
            "hold_hours": str(hold),
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
        key = class_key(
            idea=intent.tag,
            cav=labels.get("cav_label"),
            zlg=labels.get("zlg_label"),
            window=labels.get("window"),
            group=labels.get("symbol_group"),
            tf=labels.get("zone_tf"),
        )
        stat = calibration_lookup(self._calibration, key)
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

    def _liquidity_of(self, st: SymbolState, touch: Touch) -> dict[str, Any]:
        prints, path = self._touch_window(st, touch, seconds=self.config.zlg_window_s)
        books = [copy for _, copy in path]
        live = next((t for t in self.registry.touches if t.touch_id == touch.touch_id), touch)
        return liquidity_snapshot(
            prints=prints,
            books=books,
            eaten=live.tape_eaten,
            tick=self.tick_for(st.symbol),
            probe=st.book_pre or st.book,
        )

    def _stamp_touch_interval(self, st: SymbolState, touch: Touch) -> None:
        """OFI / CVD / phase belong to the 8s touch window, not the last 8s before CAV."""
        prints, path = self._touch_window(st, touch, seconds=self.config.zlg_window_s)
        liq = self._liquidity_of(st, touch)
        self._liquidity_stamped[touch.touch_id] = liq
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
            ofi=liq["ofi"],
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
            if event.stream in {"trades", "gap"}:
                self.uptime.on_event(event)
                self._uptime_dirty = True
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


def _feature_journal(row: FeatureRow | None) -> dict[str, Any]:
    """PIT 5m vector on the touch. Missing close → None. Never invents a score."""
    out: dict[str, Any] = {"hyexec_as_of": None}
    for name in HYEXEC_FEATURE_NAMES:
        out[f"hx_{name}"] = None
    if row is None:
        return out
    out["hyexec_as_of"] = row.as_of.isoformat()
    for name, value in row.vector.items():
        out[f"hx_{name}"] = None if value is None else str(value)
    return out


def _opt_px(raw: object) -> Decimal | None:
    if raw in {None, "", "null", "none"}:
        return None
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None
    return value if value > 0 else None


def _book_plus(book: Book, idea_side: str) -> bool | None:
    if not book.ready:
        return None
    imb = book.imbalance(5)
    if imb is None:
        return None
    return imb > 0 if idea_side == "buy" else imb < 0


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

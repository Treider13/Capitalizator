"""0.3.3 — print in a pre-drawn zone → touch. Outcome later, never same millisecond.

bounce: last price left ≥ bounce_away_ticks, working TF did not close beyond.
break: working TF close beyond the zone.
die: pending longer than touch_pending_timeout_h.
Zone created_as_of ≥ print time is invisible (no lookahead).
Does not open size.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import blake2s
from typing import Literal

from capitalizator.book.reconstruct import Book, _canon
from capitalizator.memory.hashlog import HashChain, touch_payload
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Bar, Zone

TouchOutcome = Literal["pending", "bounce", "break", "die"]


@dataclass(frozen=True)
class Touch:
    touch_id: str
    zone_id: str
    ts: datetime
    trade_px: Decimal
    trade_qty: Decimal
    outcome: TouchOutcome
    btc_regime: str | None = None
    tape_eaten: bool | None = None
    prs_y: Decimal | None = None
    gesture: str | None = None
    cav_label: str | None = None
    jury: str | None = None
    rho_class_id: str | None = None
    w_now: Decimal | None = None
    w_rank: Decimal | None = None
    bar_quality: str | None = None
    session_hour: int | None = None
    session_name: str | None = None
    htf_h4: str | None = None
    htf_d1: str | None = None
    poc: str | None = None
    vah: str | None = None
    val: str | None = None
    fib_trend: str | None = None
    fib_in_05_1: bool | None = None
    fib_in_ote_gold: bool | None = None
    rsi_tf: str | None = None
    rsi_value: str | None = None
    fvg_present: bool | None = None
    sweep_wick: bool | None = None
    refill_proxy: bool | None = None
    gex_bg: str | None = None
    first_fact: str | None = None
    n_cav: int | None = None
    n_zlg: int | None = None
    shadow_would: bool | None = None
    shadow_side: str | None = None
    shadow_tag: str | None = None
    skip_reason: str | None = None
    card_id: str | None = None
    ob_status: str | None = None
    bos_status: str | None = None
    idea: str | None = None
    prior_session_hi: str | None = None
    prior_session_lo: str | None = None
    cav_tf: str | None = None
    a_same: str | None = None
    a_back: str | None = None
    a_in: str | None = None
    a_opp: str | None = None
    ofi: str | None = None
    trades_in_window: int | None = None
    wall_state: str | None = None
    prs_tau: str | None = None
    btc_state: str | None = None
    btc_break_against: bool | None = None
    bearing_verdict: str | None = None
    # ОКО (INVENTION-OKO). oko_voice is a jury input; the rest is journal.
    oko_voice: int | str | None = None
    oko_label: str | None = None
    oko_regime: str | None = None
    oko_reason: str | None = None
    oko_book_trust: str | None = None
    oko_tape_trust: str | None = None
    oko_cp_prob: str | None = None
    oko_p_bounce: str | None = None
    oko_p_break: str | None = None
    oko_p_die: str | None = None
    oko_set: str | None = None
    oko_n_class: int | None = None
    oko_size_mult: str | None = None
    oko_fingerprint: str | None = None
    oko_footprint: str | None = None
    oko_footprint_side: str | None = None
    oko_oi_z: str | None = None
    oko_liq_rel: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.ts)

    @classmethod
    def create(
        cls,
        *,
        zone_id: str,
        ts: datetime,
        trade_px: Decimal,
        trade_qty: Decimal,
    ) -> Touch:
        when = require_utc(ts)
        parts = (zone_id, when.isoformat(), _canon(trade_px), _canon(trade_qty))
        payload = "|".join(parts).encode()
        return cls(
            touch_id=blake2s(payload, digest_size=16).hexdigest(),
            zone_id=zone_id,
            ts=when,
            trade_px=trade_px,
            trade_qty=trade_qty,
            outcome="pending",
        )


class Registry:
    def __init__(
        self,
        *,
        tick_size: Decimal,
        config: RegistryConfig | None = None,
        tick_for: Callable[[str], Decimal] | None = None,
    ) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        self.tick_size = tick_size
        self.config = config or load_registry()
        self.touches: list[Touch] = []
        self._zones: dict[str, Zone] = {}
        self.chain = HashChain()
        # Per-symbol tick (instruments-info). None keeps the legacy single tick.
        self._tick_for = tick_for
        # (kind, label, symbol) → n for touches archived out of memory. Journal
        # rows are the record; these keep n_cav / n_zlg exact after archiving.
        self.archived: dict[tuple[str, str, str], int] = {}
        self.n_archived = 0

    def archive_resolved(self, *, now: datetime, max_age: timedelta) -> list[Touch]:
        """Move resolved touches older than max_age out of memory, keeping label counts."""
        cutoff = require_utc(now) - max_age
        keep: list[Touch] = []
        gone: list[Touch] = []
        for touch in self.touches:
            if touch.outcome == "pending" or touch.ts >= cutoff:
                keep.append(touch)
                continue
            zone = self._zones.get(touch.zone_id)
            symbol = zone.symbol if zone is not None else ""
            if touch.cav_label:
                key = ("cav", touch.cav_label, symbol)
                self.archived[key] = self.archived.get(key, 0) + 1
            if touch.gesture:
                key = ("zlg", touch.gesture, symbol)
                self.archived[key] = self.archived.get(key, 0) + 1
            gone.append(touch)
        if gone:
            self.touches = keep
            self.n_archived += len(gone)
        return gone

    def archived_count(self, kind: str, label: str | None, symbol: str) -> int:
        if not label:
            return 0
        return self.archived.get((kind, label, symbol), 0)

    def count_label(self, kind: str, label: str | None, symbol: str) -> int:
        """In-memory touches with this label for the symbol plus archived ones."""
        if not label:
            return 0
        attr = "cav_label" if kind == "cav" else "gesture"
        live = 0
        for touch in self.touches:
            if getattr(touch, attr) != label:
                continue
            zone = self._zones.get(touch.zone_id)
            if zone is not None and zone.symbol == symbol:
                live += 1
        return live + self.archived_count(kind, label, symbol)

    def tick(self, symbol: str) -> Decimal:
        if self._tick_for is None:
            return self.tick_size
        return self._tick_for(symbol)

    def zone(self, zone_id: str) -> Zone:
        return self._zones[zone_id]

    def on_trade(self, trade: MarketEvent, zones: Sequence[Zone]) -> list[Touch]:
        if trade.stream != "trades":
            raise ValueError("on_trade expects stream=trades")
        ts = require_utc(trade.exchange_ts)
        px = Decimal(str(trade.payload["px"]))
        qty = Decimal(str(trade.payload["qty"]))
        if px <= 0 or qty <= 0:
            raise ValueError("trade px/qty must be > 0")
        opened: list[Touch] = []
        pad = self.tick(trade.symbol) * self.config.epsilon_ticks
        pending_zones = {t.zone_id for t in self.touches if t.outcome == "pending"}
        for zone in zones:
            self._zones[zone.zone_id] = zone
            if zone.symbol != trade.symbol:
                continue
            if zone.created_as_of >= ts:
                continue
            if not (zone.lo - pad <= px <= zone.hi + pad):
                continue
            if zone.zone_id in pending_zones:
                continue
            touch = Touch.create(zone_id=zone.zone_id, ts=ts, trade_px=px, trade_qty=qty)
            self.touches.append(touch)
            self.chain.append(touch_payload(zone_id=zone.zone_id, gesture="pending"))
            pending_zones.add(zone.zone_id)
            opened.append(touch)
        return opened

    def resolve(
        self,
        *,
        now: datetime,
        bars: Sequence[Bar],
        last_px: Decimal,
    ) -> list[Touch]:
        when = require_utc(now)
        changed: list[Touch] = []
        next_rows: list[Touch] = []
        for touch in self.touches:
            if touch.outcome != "pending":
                next_rows.append(touch)
                continue
            zone = self._zones.get(touch.zone_id)
            if zone is None:
                next_rows.append(touch)
                continue
            decided = self._decide(touch, zone, when, bars, last_px)
            next_rows.append(decided)
            if decided.outcome != "pending":
                changed.append(decided)
        self.touches = next_rows
        return changed

    def resolve_symbol(
        self,
        symbol: str,
        *,
        now: datetime,
        bars: Sequence[Bar],
        last_px: Decimal,
    ) -> list[Touch]:
        """Decide pending touches of one symbol. Other symbols keep last_px out."""
        when = require_utc(now)
        changed: list[Touch] = []
        next_rows: list[Touch] = []
        for touch in self.touches:
            zone = self._zones.get(touch.zone_id)
            if zone is None or touch.outcome != "pending" or zone.symbol != symbol:
                next_rows.append(touch)
                continue
            decided = self._decide(touch, zone, when, bars, last_px)
            next_rows.append(decided)
            if decided.outcome != "pending":
                changed.append(decided)
        self.touches = next_rows
        return changed

    def _decide(
        self,
        touch: Touch,
        zone: Zone,
        now: datetime,
        bars: Sequence[Bar],
        last_px: Decimal,
    ) -> Touch:
        work = [
            b
            for b in bars
            if b.tf == self.config.working_tf
            and touch.ts < b.close_ts < now
            and b.symbol == zone.symbol
        ]
        for bar in work:
            if zone.side == "support" and bar.close < zone.lo:
                return replace(touch, outcome="break")
            if zone.side == "resistance" and bar.close > zone.hi:
                return replace(touch, outcome="break")
        away = self.tick(zone.symbol) * self.config.bounce_away_ticks
        if zone.side == "support" and last_px >= zone.hi + away:
            return replace(touch, outcome="bounce")
        if zone.side == "resistance" and last_px <= zone.lo - away:
            return replace(touch, outcome="bounce")
        if now - touch.ts > timedelta(hours=self.config.touch_pending_timeout_h):
            return replace(touch, outcome="die")
        return touch

    def fill_tape(
        self,
        *,
        book: Book | None = None,
        book_pre: Book | None = None,
        trades: Sequence[MarketEvent],
        touch_id: str | None = None,
    ) -> list[Touch]:
        """Set tape_eaten from book_pre + prints in the touch window. Does not open size.

        touch_id pins one row. One book must not paint another touch.
        Several unlabeled rows without touch_id is an error.
        """
        book = book_pre if book_pre is not None else book
        if book is None:
            raise ValueError("fill_tape needs book or book_pre")
        if touch_id is not None and not any(t.touch_id == touch_id for t in self.touches):
            raise KeyError(touch_id)
        unlabeled = [t for t in self.touches if t.tape_eaten is None]
        if touch_id is None and len(unlabeled) > 1:
            raise ValueError("fill_tape needs touch_id when several touches lack tape")
        clf = TapeClassifier()
        changed: list[Touch] = []
        next_rows: list[Touch] = []
        for touch in self.touches:
            if touch_id is not None and touch.touch_id != touch_id:
                next_rows.append(touch)
                continue
            if touch.tape_eaten is not None:
                next_rows.append(touch)
                continue
            zone = self._zones[touch.zone_id]
            flag = clf.eaten(
                book=book,
                trades=trades,
                zone=zone,
                t0=touch.ts,
                tick_size=self.tick(zone.symbol),
                config=self.config,
            )
            prints = clf.prints_in_window(
                trades,
                symbol=zone.symbol,
                t0=touch.ts,
                config=self.config,
            )
            row = replace(touch, tape_eaten=flag, trades_in_window=prints)
            next_rows.append(row)
            changed.append(row)
        self.touches = next_rows
        return changed

    def _require_touch_id_if_many(self, touch_id: str | None, *, what: str) -> None:
        if touch_id is None and len(self.touches) > 1:
            raise ValueError(f"{what} needs touch_id when registry has several touches")

    def fill_btc(self, *, regime: str, touch_id: str | None = None) -> list[Touch]:
        if regime not in {"trend", "box", "news"}:
            raise ValueError(f"unknown btc regime: {regime!r}")
        return self._patch(btc_regime=regime, touch_id=touch_id)

    def fill_prs(self, *, prs_y: Decimal, touch_id: str | None = None) -> list[Touch]:
        return self._patch(prs_y=prs_y, touch_id=touch_id)

    def fill_gesture(self, *, gesture: str, touch_id: str | None = None) -> list[Touch]:
        allowed = {"DEFEND", "RETREAT", "IMPROVE", "FADE", "SILENCE"}
        if gesture not in allowed:
            raise ValueError(f"unknown gesture: {gesture!r}")
        changed = self._patch(gesture=gesture, touch_id=touch_id)
        for row in changed:
            self.chain.append(touch_payload(zone_id=row.zone_id, gesture=gesture))
        return changed

    def fill_cav(self, *, cav_label: str, touch_id: str | None = None) -> list[Touch]:
        allowed = {"REJECT", "THROUGH", "COMPRESS", "DRIFT", "NOISE"}
        if cav_label not in allowed:
            raise ValueError(f"unknown cav: {cav_label!r}")
        return self._patch(cav_label=cav_label, touch_id=touch_id)

    def fill_width(
        self,
        *,
        w_now: Decimal | None,
        w_rank: Decimal | None,
        touch_id: str | None = None,
    ) -> list[Touch]:
        """Journal only. Does not open size. Does not append the hash chain."""
        if w_now is not None and w_now < 0:
            raise ValueError("w_now must be >= 0")
        if w_rank is not None and (w_rank < 0 or w_rank > 1):
            raise ValueError("w_rank must be in [0, 1]")
        if w_rank is not None and w_now is None:
            raise ValueError("w_rank requires w_now")
        return self._patch(
            w_now=w_now,
            w_rank=w_rank,
            touch_id=touch_id,
            overwrite=True,
            require_touch_id=False,
        )

    def fill_bar_quality(self, *, quality: str, touch_id: str | None = None) -> list[Touch]:
        """Journal only. live | stagnant | illiquid. Does not append the hash chain."""
        if quality not in {"live", "stagnant", "illiquid"}:
            raise ValueError(f"unknown bar_quality: {quality!r}")
        return self._patch(
            bar_quality=quality,
            touch_id=touch_id,
            overwrite=True,
            require_touch_id=False,
        )

    def fill_sweep_wick(self, *, flag: bool, touch_id: str | None = None) -> list[Touch]:
        """Journal only. Wick beyond the zone. Does not append the hash chain."""
        return self._patch(
            sweep_wick=flag,
            touch_id=touch_id,
            overwrite=True,
            require_touch_id=False,
        )

    def fill_fvg_present(self, *, flag: bool | None, touch_id: str | None = None) -> list[Touch]:
        """Journal only. 3-candle gap or None if bars are short. Not a voice."""
        return self._patch(
            fvg_present=flag,
            touch_id=touch_id,
            overwrite=True,
            require_touch_id=False,
        )

    def fill_oko_window(
        self,
        *,
        label: str,
        fingerprint: str,
        book_trust: str | None,
        tape_trust: str | None,
        footprint: str = "NONE",
        footprint_side: str | None = None,
        touch_id: str | None = None,
    ) -> list[Touch]:
        """Shadow + Footprint facts at the 8s clock. Voice comes later, with CAV."""
        from capitalizator.oko.footprint import FOOTPRINT_LABELS
        from capitalizator.oko.shadow import SHADOW_LABELS

        if label not in SHADOW_LABELS:
            raise ValueError(f"unknown oko label: {label!r}")
        if footprint not in FOOTPRINT_LABELS:
            raise ValueError(f"unknown oko footprint: {footprint!r}")
        if footprint_side not in (None, "bid", "ask"):
            raise ValueError("footprint_side must be bid|ask|None")
        if not fingerprint:
            raise ValueError("oko fingerprint must be non-empty")
        return self._patch(
            oko_label=label,
            oko_fingerprint=fingerprint,
            oko_book_trust=book_trust,
            oko_tape_trust=tape_trust,
            oko_footprint=footprint,
            oko_footprint_side=footprint_side,
            touch_id=touch_id,
        )

    def fill_oko(
        self,
        *,
        voice: int | str,
        label: str,
        regime: str,
        reason: str,
        book_trust: str | None,
        tape_trust: str | None,
        cp_prob: str | None,
        p_bounce: str,
        p_break: str,
        p_die: str,
        pred_set: str,
        n_class: int,
        size_mult: str,
        fingerprint: str,
        footprint: str = "NONE",
        footprint_side: str | None = None,
        oi_z: str | None = None,
        liq_rel: str | None = None,
        touch_id: str | None = None,
    ) -> list[Touch]:
        """ОКО verdict. voice is a jury input: written once, like CAV / ZLG."""
        from capitalizator.jury.desk import VOICES
        from capitalizator.oko.footprint import FOOTPRINT_LABELS
        from capitalizator.oko.shadow import SHADOW_LABELS
        from capitalizator.oko.weather import REGIMES

        if voice not in VOICES:
            raise ValueError(f"oko voice must be -1|0|1|VETO, got {voice!r}")
        if label not in SHADOW_LABELS:
            raise ValueError(f"unknown oko label: {label!r}")
        if regime not in REGIMES:
            raise ValueError(f"unknown oko regime: {regime!r}")
        if footprint not in FOOTPRINT_LABELS:
            raise ValueError(f"unknown oko footprint: {footprint!r}")
        if footprint_side not in (None, "bid", "ask"):
            raise ValueError("footprint_side must be bid|ask|None")
        if n_class < 0:
            raise ValueError("n_class must be >= 0")
        if Decimal(size_mult) < 0 or Decimal(size_mult) > 1:
            raise ValueError("oko size_mult must be in [0, 1]")
        changed = self._patch(oko_voice=voice, touch_id=touch_id)
        if not changed:
            return []
        self._patch(
            touch_id=touch_id,
            overwrite=True,
            require_touch_id=False,
            oko_label=label,
            oko_regime=regime,
            oko_reason=reason,
            oko_book_trust=book_trust,
            oko_tape_trust=tape_trust,
            oko_cp_prob=cp_prob,
            oko_p_bounce=p_bounce,
            oko_p_break=p_break,
            oko_p_die=p_die,
            oko_set=pred_set,
            oko_n_class=n_class,
            oko_size_mult=size_mult,
            oko_fingerprint=fingerprint,
            oko_footprint=footprint,
            oko_footprint_side=footprint_side,
            oko_oi_z=oi_z,
            oko_liq_rel=liq_rel,
        )
        ids = {row.touch_id for row in changed}
        return [row for row in self.touches if row.touch_id in ids]

    def fill_session_hour(self, *, touch_id: str | None = None) -> list[Touch]:
        changed: list[Touch] = []
        next_rows: list[Touch] = []
        for touch in self.touches:
            if touch_id is not None and touch.touch_id != touch_id:
                next_rows.append(touch)
                continue
            row = replace(touch, session_hour=require_utc(touch.ts).hour)
            next_rows.append(row)
            changed.append(row)
        if touch_id is not None and not changed:
            raise KeyError(touch_id)
        self.touches = next_rows
        return changed

    def stamp_jury(
        self,
        *,
        idea: str = "bounce",
        n_cav: int = 0,
        n_zlg: int = 0,
        touch_id: str | None = None,
        wall_no_print: bool = False,
        btc_break_against: bool = False,
        card_bearing_verdict: str | None = None,
        cpi_window: bool = False,
        trades_in_window: int | None = None,
        btc_same_side: bool = False,
        oko_voice: int | str | None = None,
    ) -> list[Touch]:
        """Write jury + rho_class_id from already filled labels. Does not open size.

        oko_voice=None reads the row's own oko_voice (fill_oko). A row without
        ОКО is judged with oko=0 — the eye absent, not a rubber-stamp +1.
        """
        from capitalizator.jury.desk import (
            decide,
            rho_class_id,
            voices_for_bounce,
            voices_for_breakout,
            voices_for_failed_break,
            voices_for_spring,
        )
        from capitalizator.jury.desk import oko_voice as to_voice

        if idea not in {"bounce", "spring", "breakout", "failed_break"}:
            raise ValueError("idea must be bounce|spring|breakout|failed_break")
        self._require_touch_id_if_many(touch_id, what="stamp_jury")
        changed: list[Touch] = []
        next_rows: list[Touch] = []
        for touch in self.touches:
            if touch_id is not None and touch.touch_id != touch_id:
                next_rows.append(touch)
                continue
            if touch.jury is not None:
                next_rows.append(touch)
                continue
            voice_fn = {
                "bounce": voices_for_bounce,
                "spring": voices_for_spring,
                "breakout": voices_for_breakout,
                "failed_break": voices_for_failed_break,
            }[idea]
            voices = voice_fn(
                cav=touch.cav_label,
                n_cav=n_cav,
                zlg=touch.gesture,
                n_zlg=n_zlg,
                tape_eaten=touch.tape_eaten,
                btc_regime=touch.btc_regime,
                card_bearing_verdict=card_bearing_verdict or touch.bearing_verdict,
                wall_no_print=wall_no_print,
                btc_break_against=btc_break_against or bool(touch.btc_break_against),
                cpi_window=cpi_window,
                trades_in_window=trades_in_window
                if trades_in_window is not None
                else touch.trades_in_window,
                btc_same_side=btc_same_side,
                oko=to_voice(oko_voice if oko_voice is not None else touch.oko_voice),
            )
            label = decide(voices)
            class_id = None
            if touch.cav_label and touch.gesture and touch.btc_regime:
                class_id = rho_class_id(
                    setup=idea,
                    cav=touch.cav_label,
                    zlg=touch.gesture,
                    btc=touch.btc_regime,
                )
            row = replace(touch, jury=label, rho_class_id=class_id)
            next_rows.append(row)
            changed.append(row)
        if touch_id is not None and not any(t.touch_id == touch_id for t in self.touches):
            raise KeyError(touch_id)
        self.touches = next_rows
        return changed

    def _patch(
        self,
        *,
        touch_id: str | None = None,
        overwrite: bool = False,
        require_touch_id: bool = True,
        **fields: object,
    ) -> list[Touch]:
        """Voices: write empty keys only. Journal: overwrite=True may restamp every row."""
        if require_touch_id:
            self._require_touch_id_if_many(touch_id, what="fill")
        if touch_id is not None and not any(t.touch_id == touch_id for t in self.touches):
            raise KeyError(touch_id)
        changed: list[Touch] = []
        next_rows: list[Touch] = []
        for touch in self.touches:
            if touch_id is not None and touch.touch_id != touch_id:
                next_rows.append(touch)
                continue
            if overwrite:
                row = replace(touch, **fields)
            else:
                write = {key: value for key, value in fields.items() if getattr(touch, key) is None}
                if not write:
                    next_rows.append(touch)
                    continue
                row = replace(touch, **write)
            next_rows.append(row)
            changed.append(row)
        self.touches = next_rows
        return changed

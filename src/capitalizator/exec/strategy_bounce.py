"""Propose a bounce / breakout / failed-break idea. Does not send an order.

trading_mode and desk_mode must be demo|live. TAKER_OK is false (limit only).
Jury, BtcVeto, FirstMinute, MacroRules, first-fact, and PRS cut are gates
when the desk sets require_jury (isolated F1 tests leave it off).
check_tape / check_wall record in F1 and do not filter there.
require_jury (desk) applies 2.10.1: eaten or wall-without-print blocks bounce.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.btc.veto import BtcVeto
from capitalizator.card.draft import CardDraft, load_bearing_ok, require_card
from capitalizator.card.first_fact import resolve as resolve_first_fact
from capitalizator.exec.breakout_close import BreakoutClose
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.exec.smart_stop import K_ATR_DEFAULT, initial_stop
from capitalizator.jury.desk import (
    Voice,
    decide,
    voices_for_bounce,
    voices_for_breakout,
    voices_for_failed_break,
    voices_for_spring,
)
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.rules import MacroRules
from capitalizator.ops.phase import trading_mode as phase_trading_mode
from capitalizator.risk.aplus import APlus
from capitalizator.risk.budget import SessionBudget
from capitalizator.risk.halts import Halts
from capitalizator.risk.prs_cut import decide as prs_cut
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.risk.sessions import SessionPolicy
from capitalizator.screener.filters import Screener
from capitalizator.screener.universe import load_desk_universe
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Zone

TAKER_OK = False
ORDER_TYPE = "limit"
SETUP_TAG = "bounce"
MIN_R = Decimal("1.5")
DEFAULT_R = Decimal("2")
BREAK_MIN_R = Decimal("3")
# Ideas that trade *through* the zone (side flips, 3R from a real zone, no default
# multiple). `failed_break` here is the LEGACY fade-of-a-spring short. The desk
# never emits it any more: the same bar is `spring`, traded WITH the zone (D-01).
# Legacy stays for isolated callers; with require_jury (the desk) it is refused.
_BREAK_IDEAS = frozenset({"breakout", "failed_break"})
_LEGACY_FADE = "failed_break"
_IDEAS = frozenset({"bounce", "spring", "breakout", _LEGACY_FADE})


@dataclass(frozen=True)
class BounceSnapshot:
    now: datetime
    symbol: str
    price: Decimal
    tick: Decimal
    trading_mode: str
    zone: Zone | None
    zones: tuple[Zone, ...] = ()
    next_target: Zone | None = None
    spread_frac: Decimal = Decimal("0")
    typical_move: Decimal = Decimal("0.01")
    unlock_tomorrow: bool = False
    unlock_today: bool = False
    delisted: bool = False
    funding_extreme: bool = False
    volume_ok: bool = True
    calendar: Sequence[NewsRow] = field(default_factory=tuple)
    no_us_today: bool = False
    lev: Decimal = Decimal("3")
    card_path: Path | str | None = None
    card: CardDraft | None = None
    tape_eaten: bool | None = None
    wall_no_print: bool | None = None
    idea: str = "bounce"
    jury: str | None = None
    cav_label: str | None = None
    zlg_label: str | None = None
    n_cav: int = 0
    n_zlg: int = 0
    btc_regime: str | None = None
    btc_broke: bool = False
    # 3.15.5 fragility from the desk: OI peak × crowded funding × thin book, per side.
    fragile_long: bool = False
    fragile_short: bool = False
    btc_same_side: bool = False
    btc_zone_side: str = "support"
    prs_y: Decimal | None = None
    first_minute: bool = False
    close_beyond: bool = False
    allow_break: bool = False
    card_bearing_verdict: str | None = None
    gesture_n: int = 0
    trades_in_window: int | None = None
    b_verdict: str | None = None
    macro_multiplier: Decimal = Decimal("1")
    b_marks_ok: bool = True
    rvol: Decimal | None = None
    wall_state: str | None = None
    venue: str = "perp"
    spot_acked: bool = False
    # Spring: extreme of the wick that traded through the zone (bar.low / bar.high).
    wick_extreme: Decimal | None = None
    # Smart stop inputs (exec/smart_stop): working-TF ATR, absolute spread, operator mode.
    atr: Decimal | None = None
    spread_abs: Decimal | None = None
    # "structural" keeps the legacy band/wick stop (isolated F1 tests); the desk
    # passes RiskConfig.stop_mode (default hybrid).
    stop_mode: str = "structural"
    # Session window inputs (risk/sessions.py): buffer k·ATR for this window, the
    # operator's ceiling on stop distance (ATR from entry; None = no ceiling) and the
    # liquidation clusters the stop must not park on.
    k_atr: Decimal = K_ATR_DEFAULT
    max_stop_atr: Decimal | None = None
    liq_levels: tuple[Decimal, ...] = ()
    manual_stop_frac: Decimal | None = None
    # Symbol policy inputs for SessionPolicy (None = unknown, majors still pass).
    next_funding_at: datetime | None = None
    universe_rank: Mapping[str, int] | None = None
    screened: frozenset[str] | None = None
    # ОКО (INVENTION-OKO): sixth voice and its size cut. Default = eye absent.
    oko_voice: Voice = 0
    oko_size_mult: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.oko_voice not in (-1, 0, 1, "VETO"):
            raise ValueError("oko_voice must be -1|0|1|VETO")
        if self.oko_size_mult < 0 or self.oko_size_mult > 1:
            raise ValueError("oko_size_mult must be in [0, 1]; ОКО never opens size")
        if self.k_atr <= 0:
            raise ValueError("k_atr must be > 0")
        if self.max_stop_atr is not None and self.max_stop_atr <= 0:
            raise ValueError("max_stop_atr must be > 0")
        if self.macro_multiplier < 0 or self.macro_multiplier > 1:
            raise ValueError("macro_multiplier must be in [0, 1]; windows never open size")


def price_in_zone(price: Decimal, zone: Zone) -> bool:
    return zone.lo <= price <= zone.hi


def in_mid_range(
    price: Decimal,
    zones: Sequence[Zone],
    *,
    tick: Decimal | None = None,
    band_ticks: int = 0,
) -> bool:
    """True when price sits on the mid between nearest support and resistance.

    band_ticks=0 keeps the exact-tick lock used by isolated F1 tests.
    The desk passes registry mid_band_ticks.
    """
    below = [z for z in zones if z.side == "support" and z.hi < price]
    above = [z for z in zones if z.side == "resistance" and z.lo > price]
    if not below or not above:
        return False
    support = max(below, key=lambda z: z.hi)
    resist = min(above, key=lambda z: z.lo)
    mid = (support.hi + resist.lo) / 2
    if band_ticks <= 0 or tick is None:
        return price == mid
    return abs(price - mid) <= tick * band_ticks


def stop_behind(zone: Zone, tick: Decimal, away_ticks: int, *, side: str) -> Decimal:
    """Stop is behind the zone *for this side*. A short after a failed support
    sweep cannot inherit the bounce-long stop (that would sit below entry).
    """
    if tick <= 0 or away_ticks <= 0:
        raise ValueError("tick/away_ticks must be > 0")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy|sell")
    buf = tick * away_ticks
    stop = zone.lo - buf if side == "buy" else zone.hi + buf
    if stop <= 0:
        raise ValueError("stop would be <= 0")
    return stop


def stop_behind_wick(
    zone: Zone,
    wick_extreme: Decimal,
    tick: Decimal,
    away_ticks: int,
    *,
    side: str,
) -> Decimal:
    """Spring stop: behind the wick that already traded through the zone.

    The wick low (long) / high (short) is the level the market rejected; a stop
    inside it would sit where the sweep already printed.
    """
    band = stop_behind(zone, tick, away_ticks, side=side)
    buf = tick * away_ticks
    if side == "buy":
        stop = min(band, wick_extreme - buf)
    else:
        stop = max(band, wick_extreme + buf)
    if stop <= 0:
        raise ValueError("stop would be <= 0")
    return stop


def reward_multiple(idea: str) -> Decimal:
    return BREAK_MIN_R if idea in _BREAK_IDEAS else MIN_R


def default_multiple(idea: str) -> Decimal:
    """Bounce may use the product 2R default. Break ideas do not invent a target."""
    if idea in _BREAK_IDEAS:
        raise ValueError("break ideas have no default multiple")
    return DEFAULT_R


def opposing_target(
    zones: Sequence[Zone],
    *,
    side: str,
    entry: Decimal,
    symbol: str | None = None,
) -> Zone | None:
    """Nearest opposite zone beyond entry. Same symbol only. Not a fib line."""
    pool = [z for z in zones if symbol is None or z.symbol == symbol]
    if side == "buy":
        above = [z for z in pool if z.side == "resistance" and z.lo > entry]
        return min(above, key=lambda z: z.lo) if above else None
    below = [z for z in pool if z.side == "support" and z.hi < entry]
    return max(below, key=lambda z: z.hi) if below else None


def take_profit(
    side: str,
    entry: Decimal,
    stop: Decimal,
    next_zone: Zone | None,
    *,
    idea: str = "bounce",
) -> Decimal | None:
    r = abs(entry - stop)
    if r <= 0:
        return None
    need = reward_multiple(idea)
    if next_zone is not None:
        tp = next_zone.lo if side == "buy" else next_zone.hi
        reward = (tp - entry) if side == "buy" else (entry - tp)
        if reward < need * r:
            return None
        return tp
    if idea in _BREAK_IDEAS:
        return None
    span = DEFAULT_R * r
    if side == "buy":
        return entry + span
    return entry - span


class BounceStrategy:
    def __init__(
        self,
        *,
        risk: RiskEngine,
        halts: Halts,
        session: SessionPolicy | None = None,
        screener: Screener | None = None,
        registry: RegistryConfig | None = None,
        desk_mode: str | None = None,
        budget: SessionBudget | None = None,
        require_card: bool = True,
        check_load_bearing: bool = True,
        # 2.10.1 / 2.10.2: off in isolated F1 fixtures (record only); the desk turns
        # both on — an eaten level or a silent/pulled wall is not a bounce.
        check_tape: bool = False,
        check_wall: bool = False,
        require_jury: bool = False,
        macro: MacroRules | None = None,
    ) -> None:
        self.risk = risk
        self.halts = halts
        self.session = session or SessionPolicy.load()
        self.screener = screener or Screener(
            universe=load_desk_universe() if require_jury else None
        )
        self.registry = registry or load_registry()
        self.desk_mode = desk_mode if desk_mode is not None else phase_trading_mode()
        self.budget = budget if budget is not None else SessionBudget()
        self.require_card = require_card
        self.check_load_bearing = check_load_bearing
        self.check_tape = check_tape
        self.check_wall = check_wall
        self.require_jury = require_jury
        self.macro = macro if macro is not None else MacroRules(enabled=True)
        self.btc_veto = BtcVeto()
        self.first_minute = FirstMinute()
        # Journal-only: whether the last A+ idea's window would have allowed 5x.
        self.last_aplus_5x_ok: bool | None = None

    def _session_allows(self, snap: BounceSnapshot, *, lev: Decimal) -> tuple[bool, str]:
        """SessionPolicy: time × idea × symbol × funding × US-data day (one calendar)."""
        idea = snap.idea if snap.idea in _IDEAS else "bounce"
        return self.session.allows(
            snap.now,
            snap.calendar,
            idea="bounce" if idea == _LEGACY_FADE else idea,
            symbol=snap.symbol,
            lev=lev,
            no_us_today=snap.no_us_today,
            next_funding_at=snap.next_funding_at,
            rank=snap.universe_rank,
            screened=snap.screened,
        )

    def propose(self, snap: BounceSnapshot) -> Intent | None:
        if self.desk_mode not in {"demo", "live"} or snap.trading_mode not in {
            "demo",
            "live",
        }:
            return None
        if self.require_card:
            try:
                card = snap.card if snap.card is not None else require_card(
                    snap.card_path, required=True
                )
            except ValueError:
                return None
            if card is None:
                return None
            if self.check_load_bearing and not load_bearing_ok(card):
                return None
        if snap.b_verdict == "veto":
            return None
        if snap.b_verdict == "hold":
            return None
        if snap.venue == "spot_proposal" and not snap.spot_acked:
            return None
        if snap.b_verdict in {"propose", "cut_size"} and not snap.b_marks_ok:
            return None
        if TAKER_OK:
            return None
        ok, _reason = self._session_allows(snap, lev=snap.lev)
        if not ok:
            return None
        if not self.risk.allow_entry():
            return None
        if not self.halts.allow_entry():
            return None
        spot_rail = snap.venue == "spot_proposal" and snap.spot_acked
        if not spot_rail and not self.screener.ok(
            snap.symbol,
            spread_frac=snap.spread_frac,
            typical_move=snap.typical_move,
            unlock_tomorrow=snap.unlock_tomorrow,
            unlock_today=snap.unlock_today,
            delisted=snap.delisted,
            funding_extreme=snap.funding_extreme,
            volume_ok=snap.volume_ok,
        ):
            return None
        zone = snap.zone
        if zone is None or zone.symbol != snap.symbol:
            return None
        if in_mid_range(
            snap.price,
            snap.zones,
            tick=snap.tick,
            band_ticks=self.registry.mid_band_ticks if self.require_jury else 0,
        ):
            return None
        if not price_in_zone(snap.price, zone):
            return None
        idea = snap.idea if snap.idea in _IDEAS else "bounce"
        if idea == _LEGACY_FADE and self.require_jury:
            # Desk law: a wick through + close inside is a held level (spring).
            # Fading it is a shadow challenger, never a sent order.
            return None
        # 2.10.1 / 2.10.2: an eaten level or a silent/pulled wall is not a bounce. The
        # desk turns these checks on (check_tape / check_wall); F1 isolated fixtures
        # leave them off and only record.
        if idea in {"bounce", "spring"} and (
            (self.check_tape and snap.tape_eaten is True)
            or (self.check_wall and (snap.wall_no_print is True or snap.wall_state == "pulled"))
        ):
            return None
        side = "buy" if zone.side == "support" else "sell"
        if idea in _BREAK_IDEAS:
            # Desk idea_side: break of support is a short, break of resistance a long.
            side = "sell" if zone.side == "support" else "buy"
        if (side == "buy" and snap.fragile_long) or (side == "sell" and snap.fragile_short):
            # 3.15.5: no new entries on the crowded side at an OI peak with a thin book.
            return None
        if snap.symbol != "BTCUSDT" and not self.btc_veto.allow(
            alt_side=side,
            btc_broke=snap.btc_broke,
            btc_zone_side=snap.btc_zone_side,  # type: ignore[arg-type]
        ):
            return None
        macro = self.macro.decide(snap.now, snap.calendar)
        if not macro.allow:
            return None
        fact = resolve_first_fact(snap.zlg_label, snap.gesture_n)
        if self.require_jury and fact.tag == "shadow_gesture":
            return None
        if (
            self.require_jury
            and self.desk_mode in {"demo", "live"}
            and snap.card_bearing_verdict
            not in {"VERIFIED", "propose", "cut_size"}
        ):
            return None
        if prs_cut(snap.prs_y, threshold=Decimal("3")).action == "reject":
            return None
        if idea == "breakout":
            if not BreakoutClose.allow(
                enabled=snap.allow_break,
                close_beyond=snap.close_beyond,
                tape_eaten=snap.tape_eaten is True,
                btc_same=(
                    (snap.btc_regime == "box" or snap.btc_same_side)
                    and not snap.btc_broke
                ),
                first_minute=snap.first_minute,
            ):
                return None
        if snap.oko_voice == "VETO":
            return None
        if self.require_jury or snap.jury is not None or snap.cav_label or snap.zlg_label:
            voice_fn = {
                "bounce": voices_for_bounce,
                "spring": voices_for_spring,
                "breakout": voices_for_breakout,
                "failed_break": voices_for_failed_break,
            }[idea]
            voices = voice_fn(
                cav=snap.cav_label,
                n_cav=snap.n_cav,
                zlg=snap.zlg_label,
                n_zlg=snap.n_zlg,
                tape_eaten=snap.tape_eaten,
                btc_regime=snap.btc_regime,
                card_bearing_verdict=snap.card_bearing_verdict,
                wall_no_print=snap.wall_no_print is True or snap.wall_state == "pulled",
                btc_break_against=snap.btc_broke,
                btc_same_side=snap.btc_same_side,
                trades_in_window=snap.trades_in_window,
                oko=snap.oko_voice,
            )
            label = decide(voices)
            if snap.jury is not None and snap.jury != "ACCORD":
                return None
            if label != "ACCORD":
                return None
            aplus = APlus.ok(
                roles=(
                    voices.cav == 1,
                    voices.zlg == 1,
                    voices.tape == 1,
                    voices.btc == 1,
                    voices.card == 1,
                ),
                btc_same=voices.btc == 1,
            )
            if aplus and not APlus.raises_lev_in_f1():
                # A+ does not raise leverage in F1, so a window that forbids 5x is
                # not a reason to drop the trade: it is taken at the base leverage.
                # (Legacy: the same check refused the idea outright outside the
                # 16:30–19:30 MSK window, where propose was never reached anyway.)
                aplus_5x_ok, _ = self._session_allows(snap, lev=Decimal("5"))
                self.last_aplus_5x_ok = aplus_5x_ok
        try:
            stop = stop_behind(zone, snap.tick, self.registry.bounce_away_ticks, side=side)
            if idea == "spring" and snap.wick_extreme is not None:
                # The spring's invalidation is the wick that already traded, not the band.
                stop = stop_behind_wick(
                    zone,
                    snap.wick_extreme,
                    snap.tick,
                    self.registry.bounce_away_ticks,
                    side=side,
                )
        except ValueError:
            return None
        structural = stop
        try:
            # §6: volatility buffer + cluster avoidance on top of the structural level.
            smart = initial_stop(
                side=side,
                structural=structural,
                tick=snap.tick,
                atr=snap.atr,
                spread=snap.spread_abs,
                zones=[z for z in snap.zones if z.zone_id != zone.zone_id],
                k_atr=snap.k_atr,
                liq_levels=snap.liq_levels,
                max_stop_atr=snap.max_stop_atr,
                entry=snap.price,
                manual_frac=snap.manual_stop_frac,
                mode=snap.stop_mode,
            )
            stop = smart.stop
        except ValueError:
            return None
        if side == "buy" and snap.price <= stop:
            return None
        if side == "sell" and snap.price >= stop:
            return None
        tp = take_profit(side, snap.price, stop, snap.next_target, idea=idea)
        if tp is None:
            return None
        if not self.budget.allow_entry():
            return None
        if idea == "bounce":
            tag = SETUP_TAG
        elif idea == _LEGACY_FADE:
            tag = "failed_break_bounce"
        else:
            tag = idea
        size = snap.macro_multiplier
        if macro.size_mult < size:
            size = macro.size_mult
        if snap.b_verdict == "cut_size" and size > Decimal("0.5"):
            size = Decimal("0.5")
        # ОКО only cuts (INVENTION-OKO §5): min, never max.
        if snap.oko_size_mult < size:
            size = snap.oko_size_mult
        # Combined B+calendar multiplier lives on size_mult only.
        # Signer does qty * size_mult; stuffing the cut into qty would double-cut.
        intent = Intent(
            symbol=snap.symbol,
            side=side,
            entry=snap.price,
            stop=stop,
            tp=tp,
            tag=tag,
            qty=None,
            size_mult=size,
            structural=structural,
            stop_components=dict(smart.components),
        )
        # The session budget is spent by the desk *after* sizing and the EV gate
        # accept (`DeskLoop._size_and_gate`): a proposal the gates refuse must not
        # burn one of the day's three entries (audit B3).
        return intent

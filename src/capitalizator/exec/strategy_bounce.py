"""Propose a bounce / breakout / failed-break idea. Does not send an order.

trading_mode and desk_mode must be demo|live. TAKER_OK is false (limit only).
Jury, BtcVeto, FirstMinute, MacroRules, first-fact, and PRS cut are gates
when the desk sets require_jury (isolated F1 tests leave it off).
check_tape / check_wall record in F1 and do not filter there.
require_jury (desk) applies 2.10.1: eaten or wall-without-print blocks bounce.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.btc.veto import BtcVeto
from capitalizator.card.draft import CardDraft, load_bearing_ok, require_card
from capitalizator.card.first_fact import resolve as resolve_first_fact
from capitalizator.exec.breakout_close import BreakoutClose
from capitalizator.exec.first_minute import FirstMinute
from capitalizator.jury.desk import (
    decide,
    voices_for_bounce,
    voices_for_breakout,
    voices_for_failed_break,
)
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.rules import MacroRules
from capitalizator.ops.phase import trading_mode as phase_trading_mode
from capitalizator.risk.aplus import APlus
from capitalizator.risk.budget import SessionBudget
from capitalizator.risk.halts import Halts
from capitalizator.risk.prs_cut import decide as prs_cut
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.risk.session import SessionWindow
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
_BREAK_IDEAS = frozenset({"breakout", "failed_break"})


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
    btc_same_side: bool = False
    btc_zone_side: str = "support"
    prs_y: Decimal | None = None
    first_minute: bool = False
    close_beyond: bool = False
    allow_break: bool = False
    card_bearing_verdict: str | None = None
    gesture_n: int = 0
    trades_in_window: int | None = None


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
        session: SessionWindow | None = None,
        screener: Screener | None = None,
        registry: RegistryConfig | None = None,
        desk_mode: str | None = None,
        budget: SessionBudget | None = None,
        require_card: bool = True,
        check_load_bearing: bool = True,
        check_tape: bool = True,
        check_wall: bool = True,
        require_jury: bool = False,
        macro: MacroRules | None = None,
    ) -> None:
        self.risk = risk
        self.halts = halts
        self.session = session or SessionWindow()
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
        if TAKER_OK:
            return None
        ok, _reason = self.session.allows(
            snap.now,
            snap.calendar,
            lev=snap.lev,
            no_us_today=snap.no_us_today,
        )
        if not ok:
            return None
        if not self.risk.allow_entry():
            return None
        if not self.halts.allow_entry():
            return None
        if not self.screener.ok(
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
        # F1 isolated tests: check_tape / check_wall record only.
        # Desk require_jury: 2.10.1 — eaten or silent wall is not a bounce.
        _ = (self.check_tape, self.check_wall)
        idea = snap.idea if snap.idea in {"bounce", "breakout", "failed_break"} else "bounce"
        if (
            idea == "bounce"
            and self.require_jury
            and (snap.tape_eaten is True or snap.wall_no_print is True)
        ):
            return None
        side = "buy" if zone.side == "support" else "sell"
        if idea in _BREAK_IDEAS:
            # Desk idea_side: break of support is a short, break of resistance a long.
            side = "sell" if zone.side == "support" else "buy"
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
            and snap.card_bearing_verdict != "VERIFIED"
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
        if self.require_jury or snap.jury is not None or snap.cav_label or snap.zlg_label:
            voice_fn = {
                "bounce": voices_for_bounce,
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
                wall_no_print=snap.wall_no_print is True,
                btc_break_against=snap.btc_broke,
                btc_same_side=snap.btc_same_side,
                trades_in_window=snap.trades_in_window,
            )
            label = decide(voices)
            if snap.jury is not None and snap.jury != "ACCORD":
                return None
            if label != "ACCORD":
                return None
            if APlus.ok(
                roles=(
                    voices.cav == 1,
                    voices.zlg == 1,
                    voices.tape == 1,
                    voices.btc == 1,
                    voices.card == 1,
                ),
                btc_same=voices.btc == 1,
            ):
                night_ok, _ = self.session.allows(
                    snap.now,
                    snap.calendar,
                    lev=Decimal("5"),
                    no_us_today=snap.no_us_today,
                )
                if not night_ok:
                    return None
        try:
            stop = stop_behind(zone, snap.tick, self.registry.bounce_away_ticks, side=side)
        except ValueError:
            return None
        tp = take_profit(side, snap.price, stop, snap.next_target, idea=idea)
        if tp is None:
            return None
        if not self.budget.allow_entry():
            return None
        if idea == "bounce":
            tag = SETUP_TAG
        elif idea == "failed_break":
            tag = "failed_break_bounce"
        else:
            tag = idea
        intent = Intent(
            symbol=snap.symbol,
            side=side,
            entry=snap.price,
            stop=stop,
            tp=tp,
            tag=tag,
            size_mult=macro.size_mult,
        )
        self.budget.on_intent()
        return intent

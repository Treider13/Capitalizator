"""1.6.1 / 1.6.2 / 1.6.5 — propose a bounce. Does not send an order.

All gates must pass or the result is None. trading_mode must be demo.
F1: TAKER_OK is false; the intent is a limit idea only.
Gesture / BTC veto are not gates here (BtcVeto is not imported).
tape_eaten / wall_no_print apply only when check_tape / check_wall are on
(F1 defaults off). Card file is required unless tests turn the flag off.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.card.draft import CardDraft, load_bearing_ok, require_card
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.ops.phase import trading_mode as phase_trading_mode
from capitalizator.risk.budget import SessionBudget
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.risk.session import SessionWindow
from capitalizator.screener.filters import Screener
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Zone

TAKER_OK = False
ORDER_TYPE = "limit"
SETUP_TAG = "bounce"
MIN_R = Decimal("1.5")
DEFAULT_R = Decimal("2")


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
    calendar: Sequence[NewsRow] = field(default_factory=tuple)
    no_us_today: bool = False
    lev: Decimal = Decimal("3")
    card_path: Path | str | None = None
    card: CardDraft | None = None
    tape_eaten: bool = False
    wall_no_print: bool = False


def price_in_zone(price: Decimal, zone: Zone) -> bool:
    return zone.lo <= price <= zone.hi


def in_mid_range(price: Decimal, zones: Sequence[Zone]) -> bool:
    """True only when price is exactly midway between nearest support and resistance."""
    below = [z for z in zones if z.side == "support" and z.hi < price]
    above = [z for z in zones if z.side == "resistance" and z.lo > price]
    if not below or not above:
        return False
    support = max(below, key=lambda z: z.hi)
    resist = min(above, key=lambda z: z.lo)
    mid = (support.hi + resist.lo) / 2
    return price == mid


def stop_behind(zone: Zone, tick: Decimal, away_ticks: int) -> Decimal:
    if tick <= 0 or away_ticks <= 0:
        raise ValueError("tick/away_ticks must be > 0")
    buf = tick * away_ticks
    stop = zone.lo - buf if zone.side == "support" else zone.hi + buf
    if stop <= 0:
        raise ValueError("stop would be <= 0")
    return stop


def take_profit(
    side: str,
    entry: Decimal,
    stop: Decimal,
    next_zone: Zone | None,
) -> Decimal | None:
    r = abs(entry - stop)
    if r <= 0:
        return None
    if next_zone is not None:
        tp = next_zone.lo if side == "buy" else next_zone.hi
        reward = (tp - entry) if side == "buy" else (entry - tp)
        if reward < MIN_R * r:
            return None
        return tp
    if side == "buy":
        return entry + DEFAULT_R * r
    return entry - DEFAULT_R * r


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
        check_tape: bool = False,
        check_wall: bool = False,
    ) -> None:
        self.risk = risk
        self.halts = halts
        self.session = session or SessionWindow()
        self.screener = screener or Screener()
        self.registry = registry or load_registry()
        self.desk_mode = desk_mode if desk_mode is not None else phase_trading_mode()
        self.budget = budget if budget is not None else SessionBudget()
        self.require_card = require_card
        self.check_load_bearing = check_load_bearing
        self.check_tape = check_tape
        self.check_wall = check_wall

    def propose(self, snap: BounceSnapshot) -> Intent | None:
        if self.desk_mode != "demo" or snap.trading_mode != "demo":
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
        ):
            return None
        zone = snap.zone
        if zone is None or zone.symbol != snap.symbol:
            return None
        if in_mid_range(snap.price, snap.zones):
            return None
        if not price_in_zone(snap.price, zone):
            return None
        if self.check_tape and snap.tape_eaten:
            return None
        if self.check_wall and snap.wall_no_print:
            return None
        side = "buy" if zone.side == "support" else "sell"
        try:
            stop = stop_behind(zone, snap.tick, self.registry.bounce_away_ticks)
        except ValueError:
            return None
        tp = take_profit(side, snap.price, stop, snap.next_target)
        if tp is None:
            return None
        if not self.budget.allow_entry():
            return None
        intent = Intent(
            symbol=snap.symbol,
            side=side,
            entry=snap.price,
            stop=stop,
            tp=tp,
            tag=SETUP_TAG,
        )
        self.budget.on_intent()
        return intent

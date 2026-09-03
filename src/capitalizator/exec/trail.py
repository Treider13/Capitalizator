"""Trailing engine (§7 of the plan). Replaces `TradeManager.trail_stop` (an identity
function nobody called) with a state machine that emits stop moves.

Phases per position:
  0  filled           → hard stop from smart_stop; 50% TP at +1R is the exchange's
                        (paper engine / gateway trading-stop Partial)
  1  half taken       → stop follows STRUCTURE: last confirmed swing (Williams fractal,
                        n=2, same helper contour B uses) minus the buffer. Not "entry
                        because +2%" — law 15.
  2  runner           → on each closed working bar: new confirmed swing in our favour
                        → amend stop to swing ∓ buffer. Impulse bar (range > m·ATR)
                        additionally arms an exchange-side trailing stop at d·ATR so
                        a V-spike is caught by the venue between our bar closes.

Invariants (tested): a long stop only rises, a short stop only falls; the engine
never proposes a stop on the wrong side of price; every action carries its reason.
The consumer applies actions to the paper engine (`set_stop`) or to the gateway
(`amend_stop` / `set_trailing`). This module sends nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from capitalizator.card.sweep import fractals
from capitalizator.exec.smart_stop import push_past_clusters
from capitalizator.patterns.bar_quality import atr as atr_of
from capitalizator.zones.model import Bar, Zone

IMPULSE_ATR_MULT = Decimal("2")  # provenance: paper — a bar > 2 ATR is a spike (calibrate)
TRAIL_ATR_MULT = Decimal("2")  # exchange trailing distance; 2 ATR (practice floor)
K_ATR_TRAIL = Decimal("0.5")  # docs 0.5–0.7 ATR behind the swing


@dataclass(frozen=True)
class TrailAction:
    kind: str  # amend_stop | exchange_trailing | none
    new_stop: Decimal | None
    reason: str
    trailing_distance: Decimal | None = None
    active_price: Decimal | None = None


@dataclass
class TrailState:
    side: str
    entry: Decimal
    stop: Decimal
    tick: Decimal
    half_taken: bool = False
    phase: int = 0
    last_swing: Decimal | None = None
    exchange_trailing_armed: bool = False
    moves: list[tuple[str, str, str]] = field(default_factory=list)
    initial_stop: Decimal | None = None

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy|sell")
        if self.side == "buy" and self.stop >= self.entry:
            raise ValueError("buy stop must be below entry")
        if self.side == "sell" and self.stop <= self.entry:
            raise ValueError("sell stop must be above entry")
        if self.initial_stop is None:
            self.initial_stop = self.stop

    def r_px(self) -> Decimal:
        """Initial risk distance — 1R never changes after the fill."""
        assert self.initial_stop is not None
        return abs(self.entry - self.initial_stop)

    def _better(self, new_stop: Decimal) -> bool:
        return new_stop > self.stop if self.side == "buy" else new_stop < self.stop


class TrailEngine:
    def __init__(
        self,
        *,
        k_atr: Decimal = K_ATR_TRAIL,
        impulse_mult: Decimal = IMPULSE_ATR_MULT,
        trail_mult: Decimal = TRAIL_ATR_MULT,
        fractal_n: int = 2,
        mode: str = "both",  # structure | exchange_trailing | both
    ) -> None:
        if k_atr <= 0 or impulse_mult <= 0 or trail_mult <= 0 or fractal_n < 1:
            raise ValueError("trail knobs must be > 0")
        if mode not in {"structure", "exchange_trailing", "both"}:
            raise ValueError("mode must be structure|exchange_trailing|both")
        self.k_atr = k_atr
        self.impulse_mult = impulse_mult
        self.trail_mult = trail_mult
        self.fractal_n = fractal_n
        self.mode = mode

    # --- events ------------------------------------------------------------------
    def on_half(self, st: TrailState) -> TrailAction:
        """+1R half filled. Phase 1: structure trail is now allowed (never mechanical BE)."""
        st.half_taken = True
        if st.phase == 0:
            st.phase = 1
        return TrailAction("none", None, "half_taken_structure_trail_armed")

    def on_bar(
        self,
        st: TrailState,
        bars: Sequence[Bar],
        *,
        last_px: Decimal,
        zones: Sequence[Zone] = (),
        liq_levels: Sequence[Decimal] = (),
    ) -> list[TrailAction]:
        """Closed working bars (oldest→newest, same symbol/tf). Returns actions to apply."""
        out: list[TrailAction] = []
        if not bars:
            return out
        atr = atr_of(list(bars))
        buffer = self._buffer(st, atr)
        if st.phase >= 1 and self.mode in {"structure", "both"}:
            swing = self._last_swing(st, bars)
            if swing is not None:
                cand = swing - buffer if st.side == "buy" else swing + buffer
                cand = self._round(cand, st.tick, st.side)
                cand, _, _ = push_past_clusters(
                    side=st.side,
                    stop=cand,
                    tick=st.tick,
                    atr=atr,
                    zones=zones,
                    liq_levels=liq_levels,
                )
                if st._better(cand) and self._safe(st, cand, last_px):
                    st.moves.append((str(st.stop), str(cand), "swing"))
                    st.stop = cand
                    st.last_swing = swing
                    st.phase = max(st.phase, 2)
                    out.append(TrailAction("amend_stop", cand, f"swing {swing} - buffer {buffer}"))
        if (
            self.mode in {"exchange_trailing", "both"}
            and atr is not None
            and atr > 0
            and not st.exchange_trailing_armed
            and st.half_taken
        ):
            last = bars[-1]
            our_way = last.close > last.open if st.side == "buy" else last.close < last.open
            if our_way and (last.high - last.low) >= self.impulse_mult * atr:
                dist = self._round(self.trail_mult * atr, st.tick, "sell")
                st.exchange_trailing_armed = True
                out.append(
                    TrailAction(
                        "exchange_trailing",
                        None,
                        f"impulse bar {last.high - last.low} >= {self.impulse_mult}*ATR {atr}",
                        trailing_distance=dist,
                        active_price=last_px,
                    )
                )
        return out

    # --- helpers ------------------------------------------------------------------
    def _buffer(self, st: TrailState, atr: Decimal | None) -> Decimal:
        raw = self.k_atr * atr if atr is not None and atr > 0 else st.tick
        return max(st.tick, self._round(raw, st.tick, "sell"))

    def _last_swing(self, st: TrailState, bars: Sequence[Bar]) -> Decimal | None:
        highs, lows = fractals(list(bars), n=self.fractal_n)
        if st.side == "buy":
            if not lows:
                return None
            return bars[lows[-1]].low
        if not highs:
            return None
        return bars[highs[-1]].high

    @staticmethod
    def _safe(st: TrailState, stop: Decimal, last_px: Decimal) -> bool:
        """Never propose a stop on the wrong side of the last price (would fire instantly)."""
        return stop < last_px if st.side == "buy" else stop > last_px

    @staticmethod
    def _round(value: Decimal, tick: Decimal, side: str) -> Decimal:
        q = value / tick
        if side == "buy":
            return q.to_integral_value(rounding="ROUND_FLOOR") * tick
        return q.to_integral_value(rounding=ROUND_CEILING) * tick

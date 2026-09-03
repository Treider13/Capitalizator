"""Paper execution engine: the 24/7 shadow trades the real tape (W3, §5.6).

Before this, "shadow R" was ±1 from a tag (`bounce` = price wiggled 8 ticks).
Now every shadow idea, every fade challenger and every demo intent becomes a
paper order that lives against the prints:

  pending  → filled when the tape trades THROUGH the limit (conservative queue:
             a buy needs a print strictly below the limit, or at the limit with a
             seller as taker). `NaiveQueueFill` (touch = fill) is recorded next to
             it as the optimistic bound.
  open     → MAE / MFE tracked per print; +1R closes half at the limit (law 1.6.3);
             stop is a market exit at stop − slippage; TP a limit exit at tp;
             funding charged at each settlement boundary; time-stop at max_hold.
  closed   → pnl, fees (maker entry/TP, taker stop), funding, R_net = pnl_net /
             risk_usdt, MAE/MFE in R, hold time. Written to `paper_trades` and
             mirrored into the journal row. Demo-source trades move the Account.

No order leaves this module. It is deterministic on the tape (tests replay).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from capitalizator.exec.fees import FeeTable
from capitalizator.types import MarketEvent, require_utc

Side = Literal["buy", "sell"]
Source = Literal["shadow", "fade", "demo", "challenger"]
State = Literal["pending", "open", "closed"]
HALF = Decimal("0.5")


@dataclass
class PaperPosition:
    paper_id: str
    touch_id: str
    symbol: str
    side: Side
    limit_px: Decimal
    qty: Decimal
    stop: Decimal
    tp: Decimal | None
    tick: Decimal
    created_at: datetime
    valid_until: datetime
    max_hold: timedelta
    source: Source
    tag: str
    risk_usdt: Decimal
    funding_interval_min: int = 480
    state: State = "pending"
    filled_at: datetime | None = None
    entry_px: Decimal | None = None
    naive_fill_at: datetime | None = None
    qty_open: Decimal = Decimal("0")
    half_taken: bool = False
    half_px: Decimal | None = None
    half_at: datetime | None = None
    realized: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    mae_px: Decimal | None = None  # worst price seen against us
    mfe_px: Decimal | None = None  # best price seen for us
    stop_moves: list[tuple[str, str]] = field(default_factory=list)
    exit_reason: str | None = None
    exit_px: Decimal | None = None
    closed_at: datetime | None = None
    last_funding_slot: int | None = None
    prints_seen: int = 0
    # W4 trail: venue-side trailing distance (armed on an impulse bar); the stop
    # then follows the best price at this distance between our bar closes.
    trailing_distance: Decimal | None = None
    # Structural level (zone edge / spring wick) for the close-based soft exit.
    structural: Decimal | None = None
    stop_components: dict[str, str] = field(default_factory=dict)
    # Journal labels the trade was taken on (idea class stats, champion/calibrate.py).
    labels: dict[str, Any] = field(default_factory=dict)
    # The stop the trade was *taken* with. 1R is |limit − initial_stop| and never
    # changes when the stop trails (audit D-10: MAE/MFE in R drifted after a trail).
    initial_stop: Decimal | None = None
    # Queue model: volume that traded at our limit *after* we were resting there.
    # We are filled when it exceeds the depth that was ahead of us (see PaperEngine).
    queue_ahead: Decimal | None = None
    queue_traded: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.initial_stop is None:
            self.initial_stop = self.stop

    # --- geometry -----------------------------------------------------------
    @property
    def r_px(self) -> Decimal:
        base = self.initial_stop if self.initial_stop is not None else self.stop
        return abs(self.limit_px - base)

    def _favorable(self, px: Decimal) -> Decimal:
        assert self.entry_px is not None
        return (px - self.entry_px) if self.side == "buy" else (self.entry_px - px)

    def r_now(self, px: Decimal) -> Decimal | None:
        if self.entry_px is None or self.r_px == 0:
            return None
        return self._favorable(px) / self.r_px

    def to_payload(self) -> dict[str, Any]:
        def s(v: object) -> Any:
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, datetime):
                return v.isoformat()
            if isinstance(v, timedelta):
                return v.total_seconds()
            return v

        skip = {"stop_moves", "stop_components", "labels"}
        out = {k: s(v) for k, v in self.__dict__.items() if k not in skip}
        out["stop_moves"] = list(self.stop_moves)
        out["stop_components"] = dict(self.stop_components)
        out["labels"] = dict(self.labels)
        out["r_net"] = s(self.r_net())
        out["r_gross"] = s(self.r_gross())
        out["mae_r"] = s(self.mae_r())
        out["mfe_r"] = s(self.mfe_r())
        out["hold_s"] = (
            (self.closed_at - self.filled_at).total_seconds()
            if self.closed_at and self.filled_at
            else None
        )
        return out

    _DECIMALS = frozenset(
        {
            "limit_px", "qty", "stop", "tp", "tick", "risk_usdt", "entry_px", "qty_open",
            "half_px", "realized", "fees", "funding", "mae_px", "mfe_px", "exit_px",
            "trailing_distance", "structural", "initial_stop", "queue_ahead", "queue_traded",
        }
    )
    _DATETIMES = frozenset(
        {"created_at", "valid_until", "filled_at", "naive_fill_at", "half_at", "closed_at"}
    )

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> PaperPosition:
        """Inverse of `to_payload` for the open/pending twins that survive a restart."""
        kwargs: dict[str, Any] = {}
        for f in cls.__dataclass_fields__:
            if f not in raw:
                continue
            v = raw[f]
            if f in cls._DECIMALS:
                kwargs[f] = None if v in (None, "") else Decimal(str(v))
            elif f in cls._DATETIMES:
                kwargs[f] = None if v in (None, "") else datetime.fromisoformat(str(v))
            elif f == "max_hold":
                kwargs[f] = timedelta(seconds=float(v))
            elif f == "stop_moves":
                kwargs[f] = [tuple(x) for x in (v or [])]
            elif f in {"stop_components", "labels"}:
                kwargs[f] = dict(v or {})
            else:
                kwargs[f] = v
        return cls(**kwargs)

    # --- results ------------------------------------------------------------
    def pnl_net(self) -> Decimal:
        return self.realized - self.fees - self.funding

    def r_gross(self) -> Decimal | None:
        """None until closed; None forever if never filled (unfilled ≠ 0 R)."""
        if self.state != "closed" or self.risk_usdt == 0 or self.entry_px is None:
            return None
        return self.realized / self.risk_usdt

    def r_net(self) -> Decimal | None:
        if self.state != "closed" or self.risk_usdt == 0 or self.entry_px is None:
            return None
        return self.pnl_net() / self.risk_usdt

    def mae_r(self) -> Decimal | None:
        if self.mae_px is None or self.entry_px is None or self.r_px == 0:
            return None
        return -self._favorable(self.mae_px) / self.r_px

    def mfe_r(self) -> Decimal | None:
        if self.mfe_px is None or self.entry_px is None or self.r_px == 0:
            return None
        return self._favorable(self.mfe_px) / self.r_px


class PaperEngine:
    def __init__(
        self,
        *,
        fees: FeeTable | None = None,
        slippage_ticks: int = 1,
        max_hold: timedelta = timedelta(hours=6),
        funding_rate: Callable[[str], Decimal | None] | None = None,
        on_close: Callable[[PaperPosition], None] | None = None,
    ) -> None:
        self.fees = fees or FeeTable()
        self.slippage_ticks = slippage_ticks
        self.max_hold = max_hold
        self._funding_rate = funding_rate or (lambda _s: None)
        self._on_close = on_close
        self.positions: dict[str, PaperPosition] = {}
        self.closed: list[PaperPosition] = []
        self.n_submitted = 0
        # Last mark per symbol. Hard SL follows mark (venue slTriggerBy=MarkPrice).
        # Unknown mark → last print, same as before any ticker arrived.
        self._marks: dict[str, Decimal] = {}

    # --- submit ---------------------------------------------------------------
    def submit(
        self,
        *,
        paper_id: str,
        touch_id: str,
        symbol: str,
        side: Side,
        limit_px: Decimal,
        qty: Decimal,
        stop: Decimal,
        tp: Decimal | None,
        tick: Decimal,
        now: datetime,
        valid_for: timedelta,
        source: Source,
        tag: str,
        funding_interval_min: int = 480,
        max_hold: timedelta | None = None,
        structural: Decimal | None = None,
        stop_components: dict[str, str] | None = None,
        labels: Mapping[str, Any] | None = None,
        queue_ahead: Decimal | None = None,
    ) -> PaperPosition:
        if qty <= 0 or limit_px <= 0 or stop <= 0 or tick <= 0:
            raise ValueError("qty/limit/stop/tick must be > 0")
        if queue_ahead is not None and queue_ahead < 0:
            raise ValueError("queue_ahead must be >= 0")
        if side == "buy" and stop >= limit_px:
            raise ValueError("buy stop must be below limit")
        if side == "sell" and stop <= limit_px:
            raise ValueError("sell stop must be above limit")
        if paper_id in self.positions:
            raise ValueError(f"duplicate paper_id {paper_id}")
        when = require_utc(now)
        pos = PaperPosition(
            paper_id=paper_id,
            touch_id=touch_id,
            symbol=symbol,
            side=side,
            limit_px=limit_px,
            qty=qty,
            stop=stop,
            tp=tp,
            tick=tick,
            created_at=when,
            valid_until=when + valid_for,
            max_hold=max_hold if max_hold is not None else self.max_hold,
            source=source,
            tag=tag,
            risk_usdt=qty * abs(limit_px - stop),
            funding_interval_min=funding_interval_min,
            structural=structural,
            stop_components=dict(stop_components or {}),
            labels=dict(labels or {}),
            queue_ahead=queue_ahead,
        )
        self.positions[paper_id] = pos
        self.n_submitted += 1
        return pos

    # --- persistence (twins survive a desk restart) ------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        return [p.to_payload() for p in self.positions.values()]

    def restore(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """Load pending/open twins written by `snapshot`. Closed rows are ignored."""
        n = 0
        done = {p.paper_id for p in self.closed}
        for raw in rows:
            if raw.get("state") == "closed":
                continue
            pos = PaperPosition.from_payload(raw)
            if pos.paper_id in self.positions or pos.paper_id in done:
                continue
            self.positions[pos.paper_id] = pos
            n += 1
        return n

    def open_symbols(self) -> list[str]:
        return sorted({p.symbol for p in self.positions.values()})

    # --- tape -----------------------------------------------------------------
    def on_print(self, trade: MarketEvent) -> list[PaperPosition]:
        """Feed one print. Returns positions that changed state."""
        if trade.stream != "trades":
            return []
        try:
            px = Decimal(str(trade.payload["px"]))
        except (KeyError, ArithmeticError):
            return []
        taker = str(trade.payload.get("side") or "").lower()
        try:
            qty_print = Decimal(str(trade.payload.get("qty") or trade.payload.get("size") or "0"))
        except ArithmeticError:
            qty_print = Decimal("0")
        when = require_utc(trade.exchange_ts)
        changed: list[PaperPosition] = []
        for pos in list(self.positions.values()):
            if pos.symbol != trade.symbol:
                continue
            # A print older than the twin belongs to the tape replayed after a restart,
            # not to this trade: it can neither fill nor stop it (audit A2 — restored
            # twins were stopped out by history and the venue position flattened).
            if when < pos.created_at or (pos.filled_at is not None and when < pos.filled_at):
                continue
            pos.prints_seen += 1
            if pos.state == "pending":
                if when > pos.valid_until:
                    self._close_unfilled(pos, when, "expired")
                    changed.append(pos)
                    continue
                if pos.naive_fill_at is None and self._touches(pos, px):
                    pos.naive_fill_at = when
                if self._fills(pos, px, taker, qty_print):
                    self._fill(pos, when)
                    changed.append(pos)
                    # the same print cannot also stop us out
                    continue
            if pos.state == "open":
                self._track(pos, px)
                self._follow_trailing(pos, px)
                self._funding_tick(pos, when)
                if self._stop_hit(pos, self._stop_trigger_px(pos, px)):
                    self._exit(pos, when, self._stop_fill_px(pos), "stop", role="taker")
                    changed.append(pos)
                    continue
                # Exits are resting limits too: the tape must trade THROUGH them, or at
                # them with the taker on the other side — the same queue rule as the
                # entry (audit: touch-fills on exits inflated paper R).
                if not pos.half_taken and self._level_filled(pos, self._half_px(pos), px, taker):
                    self._take_half(pos, when)
                    changed.append(pos)
                if pos.tp is not None and self._level_filled(pos, pos.tp, px, taker):
                    self._exit(pos, when, pos.tp, "tp", role="maker")
                    changed.append(pos)
                    continue
                if pos.filled_at is not None and when - pos.filled_at >= pos.max_hold:
                    self._exit(pos, when, px, "time", role="taker")
                    changed.append(pos)
        return changed

    def on_clock(self, now: datetime) -> list[PaperPosition]:
        """Expire stale pending orders without a print (quiet symbol)."""
        when = require_utc(now)
        changed: list[PaperPosition] = []
        for pos in list(self.positions.values()):
            if pos.state == "pending" and when > pos.valid_until:
                self._close_unfilled(pos, when, "expired")
                changed.append(pos)
        return changed

    def on_mark(self, event: MarketEvent) -> list[PaperPosition]:
        """Hard SL trigger. Venue SL is MarkPrice; a last-price wick is not a stop.

        Trailing distance is last-price on the venue — mark does not fire that path.
        """
        if event.stream != "mark":
            return []
        try:
            px = Decimal(str(event.payload["mark"]))
        except (KeyError, ArithmeticError):
            return []
        if px <= 0:
            return []
        self._marks[event.symbol] = px
        when = require_utc(event.exchange_ts)
        changed: list[PaperPosition] = []
        for pos in list(self.positions.values()):
            if pos.symbol != event.symbol or pos.state != "open":
                continue
            if self._trailing_owns_stop(pos):
                continue
            if when < pos.created_at or (pos.filled_at is not None and when < pos.filled_at):
                continue
            if self._stop_hit(pos, px):
                self._exit(pos, when, self._stop_fill_px(pos), "stop", role="taker")
                changed.append(pos)
        return changed

    def set_stop(self, paper_id: str, new_stop: Decimal, *, reason: str) -> bool:
        """Trail hook (W4). Monotone: a long stop only rises, a short stop only falls."""
        pos = self.positions.get(paper_id)
        if pos is None or pos.state != "open":
            return False
        if pos.side == "buy" and new_stop <= pos.stop:
            return False
        if pos.side == "sell" and new_stop >= pos.stop:
            return False
        pos.stop_moves.append((str(pos.stop), str(new_stop)))
        pos.stop = new_stop
        return True

    def arm_trailing(
        self,
        paper_id: str,
        distance: Decimal,
        *,
        reason: str,
        last_px: Decimal | None = None,
    ) -> bool:
        """Venue-style trailing stop: follows the best price at `distance`, monotone."""
        pos = self.positions.get(paper_id)
        if pos is None or pos.state != "open" or distance <= 0:
            return False
        pos.trailing_distance = distance
        pos.stop_moves.append((str(pos.stop), f"trailing@{distance}"))
        self._follow_trailing(pos, last_px)
        return True

    def _follow_trailing(self, pos: PaperPosition, last_px: Decimal | None = None) -> None:
        if pos.trailing_distance is None or pos.mfe_px is None:
            return
        cand = (
            pos.mfe_px - pos.trailing_distance
            if pos.side == "buy"
            else pos.mfe_px + pos.trailing_distance
        )
        if last_px is not None:
            if pos.side == "buy" and cand >= last_px:
                return
            if pos.side == "sell" and cand <= last_px:
                return
        if (pos.side == "buy" and cand > pos.stop) or (pos.side == "sell" and cand < pos.stop):
            pos.stop_moves.append((str(pos.stop), str(cand)))
            pos.stop = cand

    def soft_exit(self, paper_id: str, px: Decimal, now: datetime) -> bool:
        """Close-based exit (smart_stop.soft_exit decided): leave at market now."""
        pos = self.positions.get(paper_id)
        if pos is None or pos.state != "open":
            return False
        self._exit(pos, require_utc(now), px, "soft", role="taker")
        return True

    def flatten(
        self, symbol: str, px: Decimal, now: datetime, *, reason: str = "flatten"
    ) -> list[PaperPosition]:
        out: list[PaperPosition] = []
        for pos in list(self.positions.values()):
            if pos.symbol != symbol:
                continue
            if pos.state == "pending":
                self._close_unfilled(pos, now, reason)
            elif pos.state == "open":
                self._exit(pos, require_utc(now), px, reason, role="taker")
            out.append(pos)
        return out

    def open_for(self, symbol: str, *, source: Source | None = None) -> list[PaperPosition]:
        return [
            p
            for p in self.positions.values()
            if p.symbol == symbol and (source is None or p.source == source)
        ]

    # --- internals --------------------------------------------------------------
    @staticmethod
    def _touches(pos: PaperPosition, px: Decimal) -> bool:
        return px <= pos.limit_px if pos.side == "buy" else px >= pos.limit_px

    @staticmethod
    def _fills(pos: PaperPosition, px: Decimal, taker: str, qty_print: Decimal) -> bool:
        """Queue model for the entry.

        Through the limit → filled (everything at our level was taken).
        At the limit with the taker against us → we are in the queue: filled when the
        volume traded at our price since we rested exceeds the depth that was ahead of
        us (`queue_ahead`, from the book at submit). Without a queue figure the rule
        degrades to the old conservative one (first print at the level fills us).
        """
        if pos.side == "buy":
            through = px < pos.limit_px
            at_level = px == pos.limit_px and taker == "sell"
        else:
            through = px > pos.limit_px
            at_level = px == pos.limit_px and taker == "buy"
        if through:
            return True
        if not at_level:
            return False
        if pos.queue_ahead is None:
            return True
        pos.queue_traded += qty_print
        return pos.queue_traded > pos.queue_ahead

    @staticmethod
    def _level_filled(pos: PaperPosition, level: Decimal, px: Decimal, taker: str) -> bool:
        """A resting exit at `level` (half / TP) fills when the tape trades through it,
        or at it with the taker on the other side of our order."""
        if pos.side == "buy":  # we sell at level
            return px > level or (px == level and taker == "buy")
        return px < level or (px == level and taker == "sell")

    @staticmethod
    def _half_px(pos: PaperPosition) -> Decimal:
        assert pos.entry_px is not None
        return pos.entry_px + pos.r_px if pos.side == "buy" else pos.entry_px - pos.r_px

    def _trailing_owns_stop(self, pos: PaperPosition) -> bool:
        """True only after the trail has actually pulled `pos.stop` to mfe ∓ distance.

        Arming the venue trail must not switch the hard SL to last: a last wick
        through the original stop would flatten the venue while MarkPrice is safe.
        """
        if pos.trailing_distance is None or pos.mfe_px is None:
            return False
        trail = (
            pos.mfe_px - pos.trailing_distance
            if pos.side == "buy"
            else pos.mfe_px + pos.trailing_distance
        )
        return pos.stop == trail

    def _stop_trigger_px(self, pos: PaperPosition, last_px: Decimal) -> Decimal:
        """Hard SL: mark when known. Last only once the exchange trail owns the stop."""
        if self._trailing_owns_stop(pos):
            return last_px
        return self._marks.get(pos.symbol, last_px)

    @staticmethod
    def _stop_hit(pos: PaperPosition, px: Decimal) -> bool:
        return px <= pos.stop if pos.side == "buy" else px >= pos.stop

    def _stop_fill_px(self, pos: PaperPosition) -> Decimal:
        slip = pos.tick * self.slippage_ticks
        return pos.stop - slip if pos.side == "buy" else pos.stop + slip

    def _fill(self, pos: PaperPosition, when: datetime) -> None:
        pos.state = "open"
        pos.filled_at = when
        pos.entry_px = pos.limit_px
        pos.qty_open = pos.qty
        pos.fees += pos.qty * pos.limit_px * self.fees.rate("maker")
        pos.mae_px = pos.limit_px
        pos.mfe_px = pos.limit_px
        pos.last_funding_slot = self._slot(when, pos.funding_interval_min)

    def _track(self, pos: PaperPosition, px: Decimal) -> None:
        if pos.mae_px is None or pos._favorable(px) < pos._favorable(pos.mae_px):
            pos.mae_px = px
        if pos.mfe_px is None or pos._favorable(px) > pos._favorable(pos.mfe_px):
            pos.mfe_px = px

    @staticmethod
    def _slot(when: datetime, interval_min: int) -> int:
        return int(when.timestamp() // (interval_min * 60))

    def _funding_tick(self, pos: PaperPosition, when: datetime) -> None:
        """Charge funding at every settlement boundary crossed while open."""
        slot = self._slot(when, pos.funding_interval_min)
        if pos.last_funding_slot is None or slot <= pos.last_funding_slot:
            return
        rate = self._funding_rate(pos.symbol)
        assert pos.entry_px is not None
        if rate is not None:
            crossings = slot - pos.last_funding_slot
            notional = pos.qty_open * pos.entry_px
            # long pays a positive rate, short receives it
            sign = Decimal("1") if pos.side == "buy" else Decimal("-1")
            pos.funding += sign * rate * notional * crossings
        pos.last_funding_slot = slot

    def _take_half(self, pos: PaperPosition, when: datetime) -> None:
        px = self._half_px(pos)
        part = pos.qty_open * HALF
        pos.realized += pos._favorable(px) * part
        pos.fees += part * px * self.fees.rate("maker")
        pos.qty_open -= part
        pos.half_taken = True
        pos.half_px = px
        pos.half_at = when

    def _exit(
        self, pos: PaperPosition, when: datetime, px: Decimal, reason: str, *, role: str
    ) -> None:
        pos.realized += pos._favorable(px) * pos.qty_open
        pos.fees += pos.qty_open * px * self.fees.rate(role)  # type: ignore[arg-type]
        pos.qty_open = Decimal("0")
        pos.exit_px = px
        pos.exit_reason = reason
        pos.closed_at = when
        pos.state = "closed"
        self._retire(pos)

    def _close_unfilled(self, pos: PaperPosition, when: datetime, reason: str) -> None:
        pos.exit_reason = reason
        pos.closed_at = require_utc(when)
        pos.state = "closed"
        self._retire(pos)

    def _retire(self, pos: PaperPosition) -> None:
        del self.positions[pos.paper_id]
        self.closed.append(pos)
        if len(self.closed) > 5000:
            del self.closed[: len(self.closed) - 5000]
        if self._on_close is not None:
            self._on_close(pos)

    def stats(self, rows: Iterable[PaperPosition] | None = None) -> dict[str, Any]:
        """Filled-and-closed trades only. Unfilled orders are counted, not scored."""
        pool = list(rows) if rows is not None else self.closed
        filled = [p for p in pool if p.entry_px is not None]
        unfilled = len(pool) - len(filled)
        rs = [p.r_net() for p in filled if p.r_net() is not None]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_win = sum(wins, Decimal("0"))
        gross_loss = -sum(losses, Decimal("0"))
        return {
            "n": len(filled),
            "n_unfilled": unfilled,
            "winrate": None if not rs else Decimal(len(wins)) / Decimal(len(rs)),
            "avg_r_net": None if not rs else sum(rs, Decimal("0")) / Decimal(len(rs)),
            "sum_r_net": None if not rs else sum(rs, Decimal("0")),
            "profit_factor": None if gross_loss == 0 else gross_win / gross_loss,
            "pnl_net": sum((p.pnl_net() for p in filled), Decimal("0")),
            "fees": sum((p.fees for p in filled), Decimal("0")),
            "funding": sum((p.funding for p in filled), Decimal("0")),
        }

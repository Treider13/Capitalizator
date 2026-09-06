"""Position tracker fed by Bybit v5 private WebSocket topics (§5.3).

Topics and fields follow https://bybit-exchange.github.io/docs/v5/websocket/private/
  position:  symbol, side (Buy/Sell/""), size, avgPrice, stopLoss, takeProfit,
             trailingStop, liqPrice, unrealisedPnl, updatedTime
  execution: symbol, side, execPrice, execQty, execFee, orderLinkId, execTime, isMaker
  order:     symbol, orderId, orderLinkId, orderStatus, side, price, qty, cumExecQty
  wallet:    coin[].coin, totalEquity / coin[].equity

The exchange is the truth. `reconcile()` compares a REST position list against the
last WS state by content (size, avgPrice, stopLoss) and returns every mismatch;
the caller turns mismatches into CRITICAL + no new entries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def _dec(raw: object, default: Decimal | None = None) -> Decimal | None:
    if raw in (None, ""):
        return default
    try:
        return Decimal(str(raw))
    except ArithmeticError:
        return default


def _ts(raw: object) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(str(raw)) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _same(a: Decimal | None, b: Decimal | None, exact: bool, tol: Decimal) -> bool:
    x, y = a or Decimal("0"), b or Decimal("0")
    if exact or x == 0 or y == 0:
        return x == y
    return abs(x - y) / max(abs(x), abs(y)) <= tol


@dataclass
class PositionSnapshot:
    symbol: str
    side: str  # buy | sell | flat
    size: Decimal
    avg_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    trailing_stop: Decimal | None
    liq_price: Decimal | None
    unrealised_pnl: Decimal | None
    updated_at: datetime | None
    position_idx: int = 0

    @property
    def flat(self) -> bool:
        return self.size == 0

    def to_payload(self) -> dict[str, Any]:
        return {
            k: (
                str(v)
                if isinstance(v, Decimal)
                else v.isoformat()
                if isinstance(v, datetime)
                else v
            )
            for k, v in self.__dict__.items()
        }


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str
    price: Decimal
    qty: Decimal
    fee: Decimal
    order_link_id: str
    exec_time: datetime | None
    is_maker: bool


@dataclass
class PositionTracker:
    on_open: Callable[[PositionSnapshot], None] | None = None
    on_flat: Callable[[PositionSnapshot], None] | None = None
    on_equity: Callable[[Decimal, datetime], None] | None = None
    positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    equity: Decimal | None = None
    equity_at: datetime | None = None
    last_ws_at: datetime | None = None
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    # REST positions nobody (WS, desk) claims. Reported on every reconcile until an
    # operator acknowledges them; never silently adopted (audit B1).
    unknown: dict[str, PositionSnapshot] = field(default_factory=dict)
    unknown_since: dict[str, datetime] = field(default_factory=dict)
    acknowledged: set[str] = field(default_factory=set)

    # --- WS topics -----------------------------------------------------------------
    def on_position(
        self, rows: Iterable[Mapping[str, Any]], *, now: datetime | None = None
    ) -> None:
        self.last_ws_at = now or datetime.now(tz=UTC)
        for row in rows:
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            size = _dec(row.get("size"), Decimal("0")) or Decimal("0")
            raw_side = str(row.get("side") or "").lower()
            side = "flat" if size == 0 else ("buy" if raw_side == "buy" else "sell")
            snap = PositionSnapshot(
                symbol=symbol,
                side=side,
                size=size,
                # v5 private `position` topic carries `entryPrice`; REST position/list
                # carries `avgPrice`. Reading only `avgPrice` here made every WS
                # position None → a mismatch on every reconcile → entries blocked for
                # ever after the first fill (audit A1).
                avg_price=_dec(row.get("entryPrice") or row.get("avgPrice")),
                stop_loss=_dec(row.get("stopLoss")),
                take_profit=_dec(row.get("takeProfit")),
                trailing_stop=_dec(row.get("trailingStop")),
                liq_price=_dec(row.get("liqPrice")),
                unrealised_pnl=_dec(row.get("unrealisedPnl")),
                updated_at=_ts(row.get("updatedTime")) or self.last_ws_at,
                position_idx=int(row.get("positionIdx") or 0),
            )
            prev = self.positions.get(symbol)
            self.positions[symbol] = snap
            was_open = prev is not None and not prev.flat
            if not snap.flat and not was_open and self.on_open is not None:
                self.on_open(snap)
            if snap.flat and was_open and self.on_flat is not None:
                self.on_flat(snap)

    def on_execution(self, rows: Iterable[Mapping[str, Any]]) -> list[Fill]:
        out: list[Fill] = []
        for row in rows:
            qty = _dec(row.get("execQty"))
            px = _dec(row.get("execPrice"))
            if qty is None or px is None:
                continue
            fill = Fill(
                symbol=str(row.get("symbol") or ""),
                side=str(row.get("side") or "").lower(),
                price=px,
                qty=qty,
                fee=_dec(row.get("execFee"), Decimal("0")) or Decimal("0"),
                order_link_id=str(row.get("orderLinkId") or ""),
                exec_time=_ts(row.get("execTime")),
                is_maker=bool(row.get("isMaker")),
            )
            self.fills.append(fill)
            out.append(fill)
        if len(self.fills) > 10_000:
            del self.fills[: len(self.fills) - 10_000]
        return out

    def on_order(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            link = str(row.get("orderLinkId") or "")
            key = link or str(row.get("orderId") or "")
            if key:
                self.orders[key] = dict(row)

    def on_wallet(self, rows: Iterable[Mapping[str, Any]], *, now: datetime | None = None) -> None:
        when = now or datetime.now(tz=UTC)
        for row in rows:
            total = _dec(row.get("totalEquity"))
            if total is None:
                coins = row.get("coin") or []
                for coin in coins:
                    if str(coin.get("coin") or "").upper() in {"USDT", "USDC"}:
                        total = _dec(coin.get("equity"))
                        break
            if total is not None:
                self.equity = total
                self.equity_at = when
                if self.on_equity is not None:
                    self.on_equity(total, when)

    # --- REST truth -----------------------------------------------------------------
    WS_LIVE_S = 60.0
    PRICE_TOL = Decimal("0.0001")  # 1 bp: venue rounding of avg/entry price

    def reconcile(
        self,
        rest_rows: Iterable[Mapping[str, Any]],
        *,
        now: datetime,
        expected: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """REST position/list is the truth. Reports:
        * `unknown_position`: REST has size for a symbol neither WS nor the desk
          (`expected`, the account's open ideas) knows about → CRITICAL;
        * field diffs (size / avg_price / stop_loss) between WS and REST when a WS
          feed exists (`last_ws_at`); without WS there is nothing to diff against.
        Afterwards the tracker adopts the REST state."""
        rest: dict[str, PositionSnapshot] = {}
        for row in rest_rows:
            size = _dec(row.get("size"), Decimal("0")) or Decimal("0")
            side = "flat" if size == 0 else str(row.get("side") or "").lower()
            symbol = str(row.get("symbol") or "")
            rest[symbol] = PositionSnapshot(
                symbol=symbol,
                side=side,
                size=size,
                avg_price=_dec(row.get("avgPrice")),
                stop_loss=_dec(row.get("stopLoss")),
                take_profit=_dec(row.get("takeProfit")),
                trailing_stop=_dec(row.get("trailingStop")),
                liq_price=_dec(row.get("liqPrice")),
                unrealised_pnl=_dec(row.get("unrealisedPnl")),
                updated_at=_ts(row.get("updatedTime")),
                position_idx=int(row.get("positionIdx") or 0),
            )
        out: list[dict[str, Any]] = []
        known = (
            {s for s, p in self.positions.items() if not p.flat}
            | set(expected or ())
            | self.acknowledged
        )
        # "WS is alive" = a frame within WS_LIVE_S, not "a frame ever arrived" (audit B3)
        has_ws = (
            self.last_ws_at is not None
            and (now - self.last_ws_at).total_seconds() < self.WS_LIVE_S
        )
        still_unknown: dict[str, PositionSnapshot] = {}
        for symbol in sorted(set(rest) | set(self.positions) | set(self.unknown)):
            a = self.positions.get(symbol)
            b = rest.get(symbol)
            if b is not None and not b.flat and symbol not in known:
                still_unknown[symbol] = b
                out.append(
                    {
                        "symbol": symbol,
                        "field": "unknown_position",
                        "ws": "absent",
                        "rest": str(b.size),
                        "since": self.unknown_since.get(symbol, now).isoformat(),
                    }
                )
                continue
            if not has_ws or a is None:
                continue
            if b is None:
                if not a.flat:
                    out.append(
                        {"symbol": symbol, "field": "size", "ws": str(a.size), "rest": "absent"}
                    )
                continue
            for name in ("size", "avg_price", "stop_loss"):
                va, vb = getattr(a, name), getattr(b, name)
                if not _same(va, vb, name == "size", self.PRICE_TOL):
                    out.append({"symbol": symbol, "field": name, "ws": str(va), "rest": str(vb)})
        stamped = [{**m, "at": now.isoformat()} for m in out]
        self.mismatches.extend(stamped)
        if len(self.mismatches) > 1000:
            del self.mismatches[: len(self.mismatches) - 1000]
        # REST is truth for what we know about; unknown positions stay unknown until
        # an operator acknowledges them (then they become known and are adopted).
        for symbol, snap in rest.items():
            if symbol in still_unknown:
                continue
            self.positions[symbol] = snap
            if snap.flat:
                # a closed position ends its acknowledgement: the next stranger on this
                # symbol must be acknowledged again (audit B4)
                self.acknowledged.discard(symbol)
        for symbol in list(self.positions):
            if symbol not in rest and not self.positions[symbol].flat and has_ws is False:
                # No WS and REST says flat: the venue is the truth.
                self.positions[symbol] = PositionSnapshot(
                    symbol=symbol, side="flat", size=Decimal("0"), avg_price=None,
                    stop_loss=None, take_profit=None, trailing_stop=None, liq_price=None,
                    unrealised_pnl=None, updated_at=now,
                )
        for symbol, snap in still_unknown.items():
            # first_seen is OUR clock at first sighting, not the venue's updatedTime
            # (which moves with funding/mark) — audit B2
            self.unknown_since.setdefault(symbol, now)
        for symbol in list(self.unknown_since):
            if symbol not in still_unknown:
                del self.unknown_since[symbol]
        self.unknown = still_unknown
        return stamped

    def acknowledge(self, symbol: str) -> bool:
        """Operator: 'this position is mine / handled'. Adopts it on the next reconcile."""
        if symbol not in self.unknown:
            return False
        self.acknowledged.add(symbol)
        return True

    def unknown_symbols(self) -> list[str]:
        return sorted(self.unknown)

    def open_symbols(self) -> list[str]:
        return sorted(s for s, p in self.positions.items() if not p.flat)

    def stop_confirmed(self, symbol: str) -> bool:
        pos = self.positions.get(symbol)
        return pos is not None and not pos.flat and pos.stop_loss is not None and pos.stop_loss > 0

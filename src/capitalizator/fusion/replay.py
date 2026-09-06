"""Deterministic event replay using the production contracts, risk and executor.

The reference exchange models queue ahead, latency, partial fills, fees and Mark
stops. It assumes small orders; replay cannot establish real market-impact capacity.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from capitalizator.fusion.archive import events
from capitalizator.fusion.atlas import train
from capitalizator.fusion.config import Config
from capitalizator.fusion.cross_market import entry_check
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.market import Market
from capitalizator.fusion.news import protect
from capitalizator.fusion.performance import metrics, venue_performance
from capitalizator.fusion.risk import Instrument
from capitalizator.fusion.store import Store
from capitalizator.news_macro.ingest import NewsRow


class ReplayVenue:
    mode = "demo"

    def __init__(
        self,
        instruments: dict[str, Instrument],
        config: Config,
        *,
        equity: float = 10000,
        latency: float = 0.2,
    ) -> None:
        if equity <= 0 or latency < 0:
            raise ValueError("invalid replay equity/latency")
        self._instruments, self.config = instruments, config
        self.cash, self.latency = equity, latency
        self.clock = 0.0
        self.markets = {s: Market(s, config, instruments[s].tick) for s in config.symbols}
        self.orders: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, dict[str, Any]] = {}
        self.fills: list[dict[str, Any]] = []
        self.equities: dict[int, float] = {}
        self.funding_slot: dict[str, int] = {}
        self.funding_settled: dict[str, int] = {}

    def instruments(self) -> dict[str, Instrument]:
        return self._instruments

    def account(self) -> tuple[float, list[Any], list[Any]]:
        positions = []
        unrealized = 0.0
        for symbol, pos in self.positions.items():
            m = self.markets[symbol]
            mark = float(m.ticker.get("markPrice") or pos["avgPrice"])
            side = 1 if pos["side"] == "Buy" else -1
            unrealized += float(pos["size"]) * (mark - float(pos["avgPrice"])) * side
            positions.append({**pos, "markPrice": str(mark)})
        active = [
            dict(o) for o in self.orders.values() if o["orderStatus"] in {"New", "PartiallyFilled"}
        ]
        return self.cash + unrealized, positions, active

    def executions(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return [r for r in self.fills if start_ms <= int(r["execTime"]) <= end_ms]

    def place(self, body: dict[str, Any]) -> dict[str, Any]:
        ident, symbol = body["orderLinkId"], body["symbol"]
        if ident in self.orders:
            raise ValueError("duplicate simulated order id")
        market = self.markets[symbol]
        price = float(body["price"])
        buy = body["side"] == "Buy"
        q = market.bids.get(price, 0.0) if buy else market.asks.get(price, 0.0)
        self.orders[ident] = {
            **body,
            "orderId": ident,
            "orderStatus": "New",
            "arrived": False,
            "ready_at": self.clock + self.latency,
            "ahead": q,
            "remaining": float(body["qty"]),
            "reduceOnly": False,
        }
        return {"orderId": ident}

    def lookup(self, symbol: str, ident: str) -> dict[str, Any] | None:
        return self.orders.get(ident)

    def cancel(self, symbol: str, ident: str) -> None:
        row = self.orders.get(ident)
        if row and row["orderStatus"] in {"New", "PartiallyFilled"}:
            row.setdefault("cancel_at", self.clock + self.latency)

    def stop(self, symbol: str, price: float) -> None:
        if symbol in self.positions:
            self.positions[symbol]["stopLoss"] = str(price)

    def close_position(self, pos: dict[str, Any], ident: str) -> None:
        if ident in self.orders:
            return
        self.orders[ident] = {
            "symbol": pos["symbol"],
            "side": "Sell" if pos["side"] == "Buy" else "Buy",
            "qty": pos["size"],
            "orderLinkId": ident,
            "orderId": ident,
            "orderStatus": "New",
            "ready_at": self.clock + self.latency,
            "remaining": float(pos["size"]),
            "reduceOnly": True,
        }

    def _fill(self, row: dict[str, Any], qty: float, price: float, maker: bool) -> None:
        symbol = row["symbol"]
        pos = self.positions.get(symbol)
        if row["reduceOnly"]:
            qty = min(qty, float(pos["size"])) if pos else 0
        if qty <= 0:
            row["orderStatus"] = "Cancelled"
            return
        inst = self._instruments[symbol]
        fee = qty * price * (inst.maker if maker else inst.taker)
        self.cash -= fee
        if row["reduceOnly"]:
            assert pos is not None
            side = 1 if pos["side"] == "Buy" else -1
            self.cash += qty * (price - float(pos["avgPrice"])) * side
            remain = float(pos["size"]) - qty
            if remain <= 1e-10:
                del self.positions[symbol]
            else:
                pos["size"] = str(remain)
        else:
            oldqty = float(pos["size"]) if pos else 0
            average = ((float(pos["avgPrice"]) * oldqty if pos else 0) + qty * price) / (
                oldqty + qty
            )
            self.positions[symbol] = {
                "symbol": symbol,
                "size": str(oldqty + qty),
                "side": row["side"],
                "avgPrice": str(average),
                "stopLoss": row["stop"],
                "positionIdx": 0,
                "liqPrice": "0",
            }
        self.fills.append(
            {
                "execId": f"replay-{len(self.fills)}",
                "symbol": symbol,
                "orderLinkId": row["orderLinkId"],
                "orderId": row["orderId"],
                "execPrice": str(price),
                "execQty": str(qty),
                "execFee": str(fee),
                "execTime": str(int(self.clock * 1000)),
                "side": row["side"],
                "isMaker": maker,
                "execType": "Trade",
            }
        )
        row["remaining"] -= qty
        row["orderStatus"] = "Filled" if row["remaining"] <= 1e-10 else "PartiallyFilled"

    def advance(self, symbol: str, kind: str, frame: dict[str, Any], at: float) -> None:
        self.clock = max(self.clock, at)
        market = self.markets[symbol]
        unique_trades = []
        if kind == "trades":
            seen = set(market.ids)
            for trade in frame["data"]:
                ident = str(trade["i"])
                if ident not in seen:
                    unique_trades.append(trade)
                    seen.add(ident)
        market.ingest(kind, frame, at)
        for row in list(self.orders.values()):
            if row["symbol"] != symbol or row["orderStatus"] not in {"New", "PartiallyFilled"}:
                continue
            if row.get("cancel_at", float("inf")) <= self.clock:
                row["orderStatus"] = "Cancelled"
                continue
            if row["ready_at"] > self.clock:
                continue
            if not row["reduceOnly"] and not row["arrived"]:
                row["arrived"] = True
                price, buy = float(row["price"]), row["side"] == "Buy"
                if (buy and market.asks and price >= min(market.asks)) or (
                    not buy and market.bids and price <= max(market.bids)
                ):
                    row["orderStatus"] = "Cancelled"
                    continue
                row["ahead"] = market.bids.get(price, 0.0) if buy else market.asks.get(price, 0.0)
            if row["reduceOnly"]:
                book = market.bids if row["side"] == "Sell" else market.asks
                for price in sorted(book, reverse=row["side"] == "Sell"):
                    self._fill(row, min(row["remaining"], book[price]), price, False)
                    if row["orderStatus"] == "Filled":
                        break
                if row["remaining"] > 1e-10:
                    row["orderStatus"] = "Cancelled"  # IOC residual
            elif kind == "trades":
                for trade in unique_trades:
                    buy = row["side"] == "Buy"
                    px, qty, limit = float(trade["p"]), float(trade["v"]), float(row["price"])
                    if not (
                        (buy and trade["S"] == "Sell" and px <= limit)
                        or (not buy and trade["S"] == "Buy" and px >= limit)
                    ):
                        continue
                    if px == limit:
                        ahead = min(qty, row["ahead"])
                        row["ahead"] -= ahead
                        qty -= ahead
                    if qty > 0:
                        self._fill(row, min(row["remaining"], qty), limit, True)
                    if row["orderStatus"] == "Filled":
                        break
        pos = self.positions.get(symbol)
        if pos and kind == "ticker":
            mark = float(market.ticker.get("markPrice") or pos["avgPrice"])
            stop = float(pos["stopLoss"])
            if (pos["side"] == "Buy" and mark <= stop) or (pos["side"] == "Sell" and mark >= stop):
                self.close_position(pos, f"stop-{symbol}-{len(self.fills)}")
            next_time = int(market.ticker.get("nextFundingTime") or 0)
            previous = self.funding_slot.get(symbol)
            if (
                previous
                and int(at * 1000) >= previous
                and self.funding_settled.get(symbol) != previous
            ):
                charge = float(pos["size"]) * mark * float(market.ticker.get("fundingRate") or 0)
                charge *= 1 if pos["side"] == "Buy" else -1
                self.cash -= charge
                self.funding_settled[symbol] = previous
                self.fills.append(
                    {
                        "execId": f"funding-{symbol}-{previous}",
                        "symbol": symbol,
                        "orderLinkId": "",
                        "execTime": str(int(at * 1000)),
                        "execFee": str(charge),
                        "execType": "Funding",
                    }
                )
            if next_time:
                self.funding_slot[symbol] = next_time
        self.equities[int(at // 86400)] = self.account()[0]


def compare(
    source: Store,
    root: Path,
    output: Path,
    config: Config,
    instruments: dict[str, Instrument],
    *,
    latency: float = 0.2,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    lanes = {}
    for variant in "ABCD":
        destination = output / f"{variant}.sqlite3"
        if destination.exists():
            raise ValueError("replay output must be new; never reuse learned test state")
        store = Store(destination)
        shared = Shared("demo")
        shared.news_required = True
        shared.news_coverage = {}
        shared.instruments, shared.broker_ready = instruments, True
        venue = ReplayVenue(instruments, config, latency=latency)
        executor = Executor(store, venue, config)
        engines = {s: Engine(s, store, shared, config, variant=variant) for s in config.symbols}
        executor.authorize = lambda order, es=engines, v=venue: (
            es[order["symbol"]].fresh(v.clock)
            and es[order["symbol"]].news_allows(v.clock)
            and entry_check(
                es[order["symbol"]].market.cross_market(),
                1 if json.loads(order["body"])["side"] == "Buy" else -1,
                v.clock,
                config,
            )
            == "ready"
        )
        lanes[variant] = (store, shared, venue, executor, engines)
    count, last_train = 0, 0
    try:
        for event in events(source, root):
            symbol, kind = event["symbol"], event["kind"]
            if symbol == "*" and kind == "news_coverage":
                for _, shared, _, _, _ in lanes.values():
                    shared.news_coverage = json.loads(event["body"])
                count += 1
                continue
            if kind == "options" and symbol in config.symbols:
                for _, shared, _, _, _ in lanes.values():
                    shared.external[symbol] = json.loads(event["body"])
                count += 1
                continue
            if symbol == "*" and kind == "news":
                calendar = []
                for row in json.loads(event["body"]):
                    row["event_time"] = datetime.fromisoformat(row["event_time"])
                    row["known_at"] = datetime.fromisoformat(row["known_at"])
                    row["assets"] = tuple(row["assets"])
                    calendar.append(NewsRow(**row))
                for store, shared, venue, executor, _ in lanes.values():
                    shared.calendar = tuple(calendar)
                    shared.news_at = event["received"]
                    venue.clock = event["received"]
                    protect(
                        store,
                        shared.calendar,
                        "demo",
                        config.symbols,
                        venue.clock,
                        config.news_post_minutes,
                    )
                    executor.tick(venue.clock, True)
                count += 1
                continue
            if symbol not in config.symbols:
                continue
            at, frame = event["received"], json.loads(event["body"])
            for store, shared, venue, executor, engines in lanes.values():
                venue.advance(symbol, kind, frame, at)
                executor.reconcile(venue.clock)
                engines[symbol].process(kind, frame, at)
                executor.tick(venue.clock, True)
            count += 1
            training_store = lanes["D"][0]
            total = int(training_store.rows("SELECT count(*) n FROM samples")[0]["n"])
            if total - last_train >= config.retrain_samples:
                model = train(training_store.samples(at, config.training_rows), config, at)
                if model:
                    for _, shared, _, _, _ in lanes.values():
                        shared.atlas = model
                last_train = total
        result: dict[str, Any] = {
            "events": count,
            "latency": latency,
            "definitions": {
                "A": "Capitalizator context sweep/zone reference; not the entire legacy DeskLoop",
                "B": "same reference with reaction contract",
                "C": "Atlas without reaction gate",
                "D": "full production Atlas and reaction contract",
            },
            "limitations": [
                "small-order replay; no endogenous market impact",
                "unclosed positions marked to market, never invented as closed trades",
                "synthetic fixtures validate mechanics, not profitability",
                "archives without spot L2 cannot authorize entries under the dual-book policy",
            ],
        }
        for variant, (store, _, venue, executor, _) in lanes.items():
            if count:
                executor.reconcile(venue.clock)
            eq = [10000.0] + list(venue.equities.values())
            daily = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
            result[variant] = {
                "venue": venue_performance(store, "demo"),
                "daily": metrics(daily, compound=True),
                "final_equity": venue.account()[0],
                "open_positions": venue.account()[1],
            }
        (output / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        return result
    finally:
        for store, *_ in lanes.values():
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline A/B/C/D receipt-time walk-forward replay")
    parser.add_argument("--userdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instruments", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--latency", type=float, default=0.2)
    args = parser.parse_args()
    config = Config.load(args.config)
    store = Store(args.userdir / "fusion.sqlite3")
    try:
        metadata = (
            json.loads(args.instruments.read_text())
            if args.instruments
            else store.meta("instruments:demo", {})
        )
        instruments = {s: Instrument(**v) for s, v in metadata.items()}
        if set(config.symbols) - instruments.keys():
            raise ValueError("record exchange instrument metadata first or supply --instruments")
        result = compare(
            store, args.userdir, args.output, config, instruments, latency=args.latency
        )
        print(json.dumps(result, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()

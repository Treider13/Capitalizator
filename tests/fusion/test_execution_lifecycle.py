"""Installed-code acceptance: synthetic model/context and an in-memory venue.

No admission method is replaced. This checks component wiring and durable state,
not discovery of profitable signals, Bybit connectivity, or venue matching quality.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from urllib.request import Request, urlopen

import pytest
from tests.fusion.daily_fixtures import seed_daily
from tests.fusion.test_contract_runtime import FakeVenue, block, instrument
from tests.fusion.test_cross_market import frame

from capitalizator.fusion.atlas import train
from capitalizator.fusion.config import Config
from capitalizator.fusion.daily import daily_context
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import encode
from capitalizator.fusion.web import ASSETS, server


class AcceptanceVenue(FakeVenue):
    """Explicit fixture acknowledgements/fills; no real exchange connection."""

    def instruments(self):
        return {s: instrument(s) for s in Config().symbols}

    def fill(self, ident, symbol, side, price, qty, at):
        fill = {
            "category": "linear",
            "execId": f"fill-{ident}",
            "orderLinkId": ident,
            "symbol": symbol,
            "side": side,
            "execPrice": str(price),
            "execQty": str(qty),
            "execFee": str(price * qty * 0.00055),
            "execTime": str(int(at * 1000)),
            "execType": "Trade",
        }
        self.fills.append(fill)
        self.venue_orders[ident].update(orderStatus="Filled", cumExecQty=str(qty))
        return fill

    def close_position(self, pos, ident):
        super().close_position(pos, ident)
        # Deterministic adverse exit, so reporting must retain a loss after fees.
        self.fill(ident, pos["symbol"], "Sell", 99.9, float(pos["size"]), time.time())


@pytest.mark.parametrize("symbol", Config().symbols)
@pytest.mark.parametrize("lost_ack", [False, True])
def test_model_contract_dispatch_fill_http_close_and_restart(tmp_path, symbol, lost_ack):
    cfg = Config()
    venue = AcceptanceVenue()
    venue.timeout_after_send = lost_ack
    r = Runtime(tmp_path, cfg)
    http = None
    thread = None
    try:
        now = time.time()
        e = r.engines[symbol]
        inst = instrument(symbol)
        r.shared.instruments = venue.instruments()
        r.shared.broker_ready = True
        # Fixtures satisfy the real news gate; coverage is not disabled.
        r.shared.calendar = ()
        r.shared.news_at = now - 1
        r.shared.news_coverage = {symbol: {"ok": True, "at": now - 1}}
        assert r.shared.news_required and not r.shared.paused
        market_frame = {
            **frame(symbol, qty=2000, at=now - 0.5, generation=0),
            "_received_monotonic": time.monotonic(),
        }
        e.market.ingest("book", market_frame, now - 0.5)
        e.market.ingest("ticker", {"data": {}}, now - 0.5)
        if cfg.requires_spot(symbol):
            e.market.ingest("spot_book", market_frame, now - 0.5)
        seed_daily(e.market, now)
        # Constant-response training data are deliberately artificial, not alpha evidence.
        rows = [
            {
                "origin": now - 1000 + i * 3,
                "available": now - 999 + i * 3,
                "x": [0.0] * 12,
                "y": [0.002, 0.1, 0.1, 1.0],
                "context": {"costs": inst.maker + inst.taker},
            }
            for i in range(256)
        ]
        model = train(rows, cfg, now - 10)
        assert model is not None and not model.report["passed"]
        r.shared.atlas = model
        with r.store.transaction() as db:
            db.execute(
                "INSERT INTO models VALUES(?,?,?,?)",
                (model.version, now, encode(model.body), encode(model.report)),
            )
        r.store.put_meta("active_model", model.version)
        for i in range(cfg.context_blocks):
            e.market.blocks.append(block(ident=i + 1, at=now - 100 + i))
        origin = block(ident=33, at=now - 0.2, close=100)
        origin = replace(
            origin,
            context={
                **origin.context,
                "sweep_extreme": 99.5,
                "ask": 100.02,
                "bid": 100,
                "atr": 0.1,
                "daily": daily_context(e.market.structure.cache["1d"], 100, now),
                "pairing": {
                    "allowed": True,
                    "retracement": 0.75,
                    "target": 130,
                    "regime": "trend",
                    "anchors": {"low": 90, "high": 130},
                },
            },
        )
        r.executor = Executor(
            r.store, venue, cfg, entry_lock=r.shared.entry_lock, authorize=r._authorize_send
        )
        r.executor.reconcile(now - 0.3)
        e.on_block(origin)
        assert e.contract_state == "observing"
        assert not r.store.rows("SELECT * FROM orders")
        confirmation = replace(
            origin,
            id=34,
            at=now - 0.1,
            flow=0.5,
            refill=0.5,
            low=99.8,
            context={**origin.context, "sweep": 0},
        )
        e.on_block(confirmation)
        order = r.store.rows("SELECT * FROM orders")[0]
        assert e.contract_state == "confirmed" and order["state"] == "pending"
        assert order["reserve"] > 0
        r.shared.snapshots[symbol] = e.market.snapshot()
        assert r._authorize_send(order)
        r.executor.tick(time.time(), True)
        assert len(venue.sent) == 1
        assert r.store.rows("SELECT state FROM orders")[0]["state"] == (
            "unknown" if lost_ack else "accepted"
        )

        # Replace both SQLite connection and Executor before any fill notification.
        r.close()
        r = Runtime(tmp_path, cfg)
        assert r.shared.atlas.version == model.version
        r.executor = Executor(
            r.store, venue, cfg, entry_lock=r.shared.entry_lock, authorize=r._authorize_send
        )
        r.executor.reconcile(time.time())
        assert r.store.rows("SELECT state FROM orders")[0]["state"] == "accepted"
        assert len(venue.sent) == 1
        spec = json.loads(order["body"])
        qty = float(spec["qty"])
        fill = venue.fill(order["id"], symbol, "Buy", 100, qty, time.time())
        venue.positions = [
            {
                "symbol": symbol,
                "side": "Buy",
                "size": str(qty),
                "avgPrice": "100",
                "markPrice": "100",
                "stopLoss": "0",
            }
        ]
        for _ in range(2):
            r.executor.private({"topic": "execution", "data": [fill]}, time.time())
        r.executor.reconcile(time.time())
        assert float(venue.positions[0]["stopLoss"]) == float(spec["stop"])
        assert r.store.rows("SELECT state FROM orders")[0]["state"] == "filled"
        assert r.status()["performance"]["executions"] == 1

        http = server(r, 0)
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        with urlopen(base, timeout=5) as response:
            page = response.read().decode()
        token = re.search(r"const token='([^']+)'", page)[1]
        for asset, (content, _) in ASSETS.items():
            with urlopen(base + asset, timeout=5) as response:
                assert response.read() == content and content
        request = Request(
            base + "/api/flatten",
            data=b"{}",
            headers={"X-Control-Token": token, "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            assert json.load(response)["paused"]
        r.executor.tick(time.time(), False)
        for _ in range(2):
            r.executor.reconcile(time.time())
        r.executor.tick(time.time(), False)
        assert not venue.positions and len(venue.closes) == 1
        assert r.store.rows("SELECT state FROM orders")[0]["state"] == "closed"
        with urlopen(base + "/api/status", timeout=5) as response:
            status = json.load(response)
        report = status["performance"]
        expected = qty * (99.9 - 100) - qty * (100 + 99.9) * 0.00055
        assert report["executions"] == 2 and report["closed_episodes"] == 1
        assert report["realized_net"] == pytest.approx(expected)
        assert report["realized_net"] < 0 and not report["incomplete_inventory"]
        assert status["paused"]
        http.shutdown()
        thread.join(5)
        http.server_close()
        http = None
        r.close()
        r = Runtime(tmp_path, cfg)
        r.executor = Executor(r.store, venue, cfg, authorize=r._authorize_send)
        r.executor.reconcile(time.time())
        r.executor.tick(time.time(), False)
        assert r.status()["performance"]["realized_net"] == pytest.approx(expected)
        assert r.shared.paused and len(venue.sent) == len(venue.closes) == 1
        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "lost_ack": lost_ack,
                    "sends": len(venue.sent),
                    "closes": len(venue.closes),
                    "executions": report["executions"],
                    "episodes": report["closed_episodes"],
                    "restart_preserved": True,
                    "scope": "synthetic component acceptance; not exchange/PnL validation",
                }
            )
        )
    finally:
        if http is not None:
            http.shutdown()
            thread.join(5)
            http.server_close()
        r.close()

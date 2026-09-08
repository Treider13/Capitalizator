"""Run real actors, SQLite, trainer process and HTTP on synthetic data, without a venue.

This checks service plumbing, not production throughput or trading profitability.
Run with OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python tools/verify_fusion_runtime.py.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from capitalizator.fusion.config import Config
from capitalizator.fusion.model_audit import audit
from capitalizator.fusion.risk import Instrument
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.web import server


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--production-blocks", action="store_true")
    args = p.parse_args()
    if not 10 <= args.seconds <= 3600:
        p.error("seconds must be 10..3600")
    cfg = (
        Config()
        if args.production_blocks
        else Config(block_trades=2, block_seconds=0.001, context_blocks=4, horizon_blocks=2)
    )
    with tempfile.TemporaryDirectory(prefix="fusion-service-") as folder:
        r = Runtime(Path(folder), cfg)
        r.shared.paused = True
        for symbol in cfg.symbols:
            r.shared.public_instruments[symbol] = Instrument(
                symbol, 0.01, 0.001, 0.001, 1, 10000, 10, 0.0002, 0.00055, 480
            )
        http = server(r, 0)
        thread = threading.Thread(target=http.serve_forever, name="test-console")
        errors: list[str] = []
        stop = threading.Event()
        counts = {"frames": 0, "peak_pending": 0, "health_checks": 0}

        def feed() -> None:
            seq = 0
            try:
                while not stop.is_set():
                    seq += 1
                    stamp = int(time.time() * 1000)
                    price = 100 + math.sin(seq / 20) * 0.005
                    for symbol in cfg.symbols:
                        book = {
                            "topic": f"orderbook.50.{symbol}",
                            "type": "snapshot" if seq == 1 else "delta",
                            "ts": stamp,
                            "data": {
                                "s": symbol,
                                "u": seq,
                                "seq": seq,
                                "b": [["99.99", str(2000 + seq % 7)]],
                                "a": [["100.01", str(1800 + seq % 9)]],
                            },
                        }
                        r.callback(book)
                        r.callback(
                            {
                                "topic": f"publicTrade.{symbol}",
                                "data": [
                                    {
                                        "T": stamp,
                                        "s": symbol,
                                        "S": "Buy" if seq % 3 else "Sell",
                                        "v": "1",
                                        "p": str(price),
                                        "i": f"{symbol}-{seq}",
                                    }
                                ],
                            }
                        )
                        counts["frames"] += 2
                        if cfg.requires_spot(symbol):
                            r._spot_event(symbol, "spot_book", book, 0, r.epoch)
                            counts["frames"] += 1
                        if seq % 10 == 1:
                            r.callback(
                                {
                                    "topic": f"tickers.{symbol}",
                                    "data": {
                                        "markPrice": str(price),
                                        "fundingRate": "0",
                                        "openInterest": "1000",
                                    },
                                }
                            )
                            counts["frames"] += 1
                    stop.wait(0.05)
            except BaseException as exc:
                errors.append(repr(exc))

        producer = threading.Thread(target=feed, name="synthetic-feed")
        started = time.monotonic()
        try:
            r.start(public=False)
            thread.start()
            producer.start()
            while time.monotonic() - started < args.seconds:
                with urlopen(f"http://127.0.0.1:{http.server_port}/api/health", timeout=5) as reply:
                    health = json.load(reply)
                assert health["healthy"], health
                counts["health_checks"] += 1
                status = r.status()
                counts["peak_pending"] = max(
                    counts["peak_pending"], sum(q["pending"] for q in status["queues"])
                )
                assert not status["halted"], status["reason"]
                assert not errors, errors
                stop.wait(1)
            stop.set()
            producer.join(5)
            rows = r.store.samples(time.time(), 32768, cfg.version)
            assert len(rows) >= 128, len(rows)
            assert r.shared.atlas is not None, "trainer did not publish a model"
            assert not r.store.rows("SELECT * FROM orders"), "paused test submitted an order"
            result = {
                "kind": "synthetic_local_service_no_exchange",
                "production_block_settings": args.production_blocks,
                "policy": cfg.version,
                "seconds": time.monotonic() - started,
                **counts,
                "symbols": list(cfg.symbols),
                "samples": len(rows),
                "models": r.store.rows("SELECT count(*) AS n FROM models")[0]["n"],
                "health": r.health(),
                "worker_errors": dict(r.supervisor.errors),
                "rejected": sum(q["rejected"] for q in status["queues"]),
                "paused": status["paused"],
                "orders": 0,
                "walk_forward": audit(rows, cfg),
                "limitations": (
                    "Synthetic prices; no Docker, network or venue matching."
                ),
            }
        finally:
            stop.set()
            if producer.is_alive():
                producer.join(5)
            if thread.is_alive():
                http.shutdown()
                thread.join(5)
            http.server_close()
            r.close()
        result["shutdown_workers_alive"] = [t.name for t in r.supervisor.threads if t.is_alive()]
        assert not result["shutdown_workers_alive"]
        print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

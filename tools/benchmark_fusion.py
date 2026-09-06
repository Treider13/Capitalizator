"""Synthetic local latency benchmark. No market-performance claims or network calls.

PYTHONPATH=src python tools/benchmark_fusion.py --events 5000
Includes durable SQLite FULL writes and two competing market actors.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=5000)
    args = parser.parse_args()
    if args.events < 1:
        raise ValueError("events must be positive")
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "bench.sqlite")
        shared, config = Shared(), Config()
        engines = [Engine(s, store, shared, config) for s in config.symbols]
        barrier = threading.Barrier(len(engines) + 1)
        timings = [[] for _ in engines]
        errors = []

        def work(index):
            engine = engines[index]
            try:
                barrier.wait()
                engine.process(
                    "book",
                    {
                        "type": "snapshot",
                        "data": {"u": 1, "b": [["100", "10"]], "a": [["101", "10"]]},
                    },
                    100,
                )
                for i in range(args.events):
                    start = time.perf_counter_ns()
                    engine.process(
                        "book",
                        {
                            "type": "delta",
                            "data": {"u": i + 2, "b": [["100", str(10 + i % 2)]], "a": []},
                        },
                        100 + i * 0.001,
                    )
                    timings[index].append((time.perf_counter_ns() - start) / 1e6)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=work, args=(i,)) for i in range(len(engines))]
        for t in threads:
            t.start()
        start = time.perf_counter()
        barrier.wait()
        for t in threads:
            t.join(60)
        elapsed = time.perf_counter() - start
        alive = [t.name for t in threads if t.is_alive()]
        if alive or errors:
            raise RuntimeError(str({"alive": alive, "errors": errors}))
        result = {
            "kind": "synthetic_local_two_actors_durable_sqlite_FULL",
            "seconds": elapsed,
            "events": sum(map(len, timings)),
            "events_per_second": sum(map(len, timings)) / elapsed,
            "symbols": {
                engine.symbol: {
                    "events": len(ts),
                    **dict(
                        zip(
                            ("p50_ms", "p95_ms", "p99_ms", "max_ms"),
                            map(float, np.percentile(ts, [50, 95, 99, 100])),
                            strict=True,
                        )
                    ),
                }
                for engine, ts in zip(engines, timings, strict=True)
            },
            "journal_rows": store.rows("SELECT count(*) AS n FROM events")[0]["n"],
            "limitations": "Synthetic book only; excludes network, inference and exchange matching",
        }
        print(json.dumps(result, indent=2))
        store.close()


if __name__ == "__main__":
    main()

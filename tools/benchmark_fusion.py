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

from capitalizator.fusion.atlas import train
from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.store import Store
from capitalizator.fusion.training import TrainingProcess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=5000)
    parser.add_argument("--training-rows", type=int, default=0)
    parser.add_argument("--isolated-training", action="store_true")
    args = parser.parse_args()
    if args.events < 1:
        raise ValueError("events must be positive")
    if args.training_rows and args.training_rows < 128:
        raise ValueError("training benchmark needs at least 128 rows")
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "bench.sqlite")
        shared, config = Shared(), Config()
        engines = [Engine(s, store, shared, config) for s in config.symbols]
        barrier = threading.Barrier(len(engines) + 1 + bool(args.training_rows))
        timings = [[] for _ in engines]
        errors = []
        done = threading.Event()
        fits = []
        rng = np.random.default_rng(0)
        training = [
            {
                "origin": 100 + i * 6,
                "available": 124 + i * 6,
                "x": rng.normal(size=12).tolist(),
                "y": [float(rng.normal(0, 0.001)), 0.0, 0.0, 24.0],
                "context": {"costs": 0.0012},
            }
            for i in range(args.training_rows)
        ]

        def fit():
            isolated = TrainingProcess() if args.isolated_training else None
            try:
                barrier.wait()
                while not done.is_set():
                    start = time.perf_counter()
                    model = (
                        isolated.fit(training, config, float("inf"), done)
                        if isolated
                        else train(training, config, float("inf"))
                    )
                    if done.is_set():
                        return
                    if model is None:
                        raise RuntimeError("training benchmark did not fit a model")
                    fits.append(time.perf_counter() - start)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                if isolated:
                    isolated.close()

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
        trainer = threading.Thread(target=fit) if training else None
        if trainer:
            trainer.start()
        start = time.perf_counter()
        barrier.wait()
        for t in threads:
            t.join(60)
        elapsed = time.perf_counter() - start
        done.set()
        if trainer:
            trainer.join(60)
        alive = [t.name for t in threads if t.is_alive()]
        if trainer and trainer.is_alive():
            alive.append(trainer.name)
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
            "concurrent_training": {
                "isolated": args.isolated_training,
                "rows": len(training),
                "fits": len(fits),
                "fit_seconds": fits,
            },
            "limitations": "Synthetic book only; excludes network, inference and exchange matching",
        }
        print(json.dumps(result, indent=2))
        store.close()


if __name__ == "__main__":
    main()

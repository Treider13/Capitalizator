"""One bounded model worker, isolated from market actors' Python interpreter."""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
from multiprocessing.connection import Connection
from typing import Any

from capitalizator.fusion.atlas import Atlas, train
from capitalizator.fusion.config import Config


def _worker(connection: Connection) -> None:
    from threadpoolctl import threadpool_limits

    # Only this child process changes native thread pools and scheduling priority.
    # Small ridge systems do not benefit from competing BLAS thread teams.
    with threadpool_limits(limits=1, user_api="blas"):
        if hasattr(os, "nice"):
            os.nice(5)
        try:
            while True:
                job = connection.recv()
                if job is None:
                    return
                rows, config, at = job
                try:
                    connection.send((True, train(rows, config, at)))
                except Exception as exc:
                    connection.send((False, f"{type(exc).__name__}: {exc}"))
        except EOFError:
            return
        finally:
            connection.close()


class TrainingProcess:
    """Single in-flight fit; no unbounded submission queue or shared mutable model."""

    def __init__(self) -> None:
        context = mp.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_worker, args=(child,), name="atlas-fit")
        self.process.start()
        child.close()

    def fit(
        self, rows: list[dict[str, Any]], config: Config, at: float, stop: threading.Event
    ) -> Atlas | None:
        if stop.is_set():
            return None
        self.connection.send((rows, config, at))
        while not stop.is_set():
            if self.connection.poll(0.1):
                ok, value = self.connection.recv()
                if not ok:
                    raise RuntimeError("model worker: " + str(value))
                if value is not None and not isinstance(value, Atlas):
                    raise TypeError("invalid model worker response")
                return value
            if not self.process.is_alive():
                raise RuntimeError("model worker exited without result")
        return None

    def close(self) -> None:
        try:
            if self.process.is_alive():
                try:
                    self.connection.send(None)
                except (BrokenPipeError, EOFError, OSError):
                    pass  # A crashed child has no remaining result to preserve.
                self.process.join(1)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(1)
            if self.process.is_alive():
                raise RuntimeError("model worker failed to terminate")
        finally:
            self.connection.close()

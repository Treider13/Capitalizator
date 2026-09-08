"""One bounded model worker, isolated from market actors' Python interpreter."""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
import traceback
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
                except Exception:
                    connection.send((False, traceback.format_exc()))
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
        self.io_thread: threading.Thread | None = None
        self.fit_lock = threading.Lock()
        self.unusable = False
        self.closed = False
        self.process.start()
        child.close()

    def fit(
        self, rows: list[dict[str, Any]], config: Config, at: float, stop: threading.Event
    ) -> Atlas | None:
        if stop.is_set():
            return None
        if not self.fit_lock.acquire(blocking=False):
            raise RuntimeError("model worker already has an in-flight job")
        try:
            if self.closed or self.unusable:
                raise RuntimeError("model worker cannot reuse a closed or interrupted pipe")
            deadline = time.monotonic() + config.training_timeout_s
            done = threading.Event()
            result: dict[str, Any] = {"phase": "send"}

            def exchange() -> None:
                try:
                    self.connection.send((rows, config, at))
                    result["phase"] = "receive"
                    result["response"] = self.connection.recv()
                except BaseException as exc:
                    result["error"] = exc
                finally:
                    done.set()

            # Pipe.send and partial Pipe.recv can both block. One bounded exchange
            # thread owns the pipe; cancellation kills its peer and invalidates it.
            self.io_thread = threading.Thread(target=exchange, name="atlas-ipc", daemon=True)
            self.io_thread.start()
            while not done.wait(0.05):
                if stop.is_set():
                    self.unusable = True
                    return None
                if time.monotonic() >= deadline:
                    self.unusable = True
                    raise TimeoutError(
                        f"model worker exceeded {config.training_timeout_s}s "
                        f"during {result['phase']}; pid={self.process.pid}"
                    )
            self.io_thread.join(0.1)
            if "error" in result:
                self.unusable = True
                self.process.join(0.1)
                raise RuntimeError(
                    f"model worker pipe failed during {result['phase']}; "
                    f"pid={self.process.pid} exitcode={self.process.exitcode}"
                ) from result["error"]
            if stop.is_set():
                return None
            ok, value = result["response"]
            if not ok:
                raise RuntimeError("model worker: " + str(value))
            if value is not None and not isinstance(value, Atlas):
                raise TypeError("invalid model worker response")
            return value
        finally:
            try:
                if self.unusable:
                    self._stop_process()
            finally:
                self.fit_lock.release()

    def _stop_process(self) -> None:
        # Never send a shutdown message over a possibly full/broken data pipe.
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(0.5)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(1)
        if self.process.is_alive():
            raise RuntimeError("model worker failed to terminate")
        if self.io_thread is not None:
            self.io_thread.join(1)
            if self.io_thread.is_alive():
                raise RuntimeError("model worker IPC did not terminate after peer exit")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.unusable = True
        try:
            # EOF requests an idle child's graceful exit without a pipe send or
            # a shared semaphore that might be owned by a stopped child.
            if self.io_thread is None or not self.io_thread.is_alive():
                self.connection.close()
            self.process.join(0.2)
            self._stop_process()
        finally:
            self.connection.close()

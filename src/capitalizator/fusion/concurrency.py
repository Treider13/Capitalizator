"""Bounded fair mailboxes. Overflow is explicit, never silent market-data loss."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any


class FairLock:
    """FIFO admission for short database transactions; deliberately non-reentrant."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.next_ticket = 0
        self.serving = 0

    def __enter__(self) -> FairLock:
        with self.condition:
            ticket = self.next_ticket
            self.next_ticket += 1
            self.condition.wait_for(lambda: ticket == self.serving)
        return self

    def __exit__(self, *args: object) -> None:
        with self.condition:
            self.serving += 1
            self.condition.notify_all()


class Mailbox:
    """FIFO within each key, round robin between keys, finite queue and waits."""

    def __init__(self, capacity: int, quantum: int = 1) -> None:
        if capacity < 1 or quantum < 1:
            raise ValueError("positive capacity/quantum required")
        self.capacity, self.quantum = capacity, quantum
        self.condition = threading.Condition()
        self.queues: dict[str, deque[Any]] = {}
        self.ready: deque[str] = deque()
        self.count = 0
        self.closed = False
        self.rejected = 0

    def put(self, key: str, item: Any) -> bool:
        with self.condition:
            if self.closed or self.count >= self.capacity:
                self.rejected += 1
                return False
            q = self.queues.setdefault(key, deque())
            if not q:
                self.ready.append(key)
            q.append(item)
            self.count += 1
            self.condition.notify()
            return True

    def get(self, timeout: float = 0.1) -> list[Any]:
        with self.condition:
            self.condition.wait_for(lambda: self.count or self.closed, timeout=timeout)
            if not self.ready:
                return []
            key = self.ready.popleft()
            q = self.queues[key]
            out = [q.popleft() for _ in range(min(self.quantum, len(q)))]
            self.count -= len(out)
            if q:
                self.ready.append(key)
            else:
                del self.queues[key]
            return out

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()

    def status(self) -> dict[str, Any]:
        with self.condition:
            return {
                "pending": self.count,
                "keys": len(self.queues),
                "rejected": self.rejected,
                "closed": self.closed,
            }


class Supervisor:
    """Worker failure latches a shared halt. No unobserved background exceptions."""

    def __init__(self, on_failure: Callable[[str, BaseException], None] | None = None) -> None:
        self.stop = threading.Event()
        self.failed = threading.Event()
        self.lock = threading.Lock()
        self.threads: list[threading.Thread] = []
        self.errors: dict[str, str] = {}
        self.heartbeats: dict[str, float] = {}
        self.on_failure = on_failure

    def beat(self, name: str) -> None:
        with self.lock:
            self.heartbeats[name] = time.monotonic()

    def start(self, name: str, fn: Any, *, allow_return: bool = False) -> None:
        def run() -> None:
            try:
                fn()
                if not self.stop.is_set() and not allow_return:
                    raise RuntimeError("worker returned before shutdown was requested")
            except BaseException as exc:
                with self.lock:
                    self.errors[name] = f"{type(exc).__name__}: {exc}"
                self.failed.set()
                if self.on_failure is not None:
                    try:
                        self.on_failure(name, exc)
                    except Exception:
                        logging.getLogger(__name__).exception("worker %s diagnostics failed", name)
                else:
                    logging.getLogger(__name__).exception("worker %s failed", name)

        thread = threading.Thread(name=name, target=run, daemon=False)
        with self.lock:
            self.heartbeats[name] = time.monotonic()
            self.threads.append(thread)
            try:
                thread.start()
            except BaseException:
                self.threads.remove(thread)
                self.heartbeats.pop(name, None)
                raise

    def join(self, timeout: float = 15.0) -> list[str]:
        self.stop.set()
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
        return [t.name for t in self.threads if t.is_alive()]

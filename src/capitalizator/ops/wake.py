"""Wake-on-event for the desk and signer. Sleep is only an idle deadline.

In-process: `Wake` is a threading.Event. Cross-process: `StampWake` touches a
regular file under `vault.root / "wake"` (never a FIFO — vault walks reject
non-regular files) and waits until mtime changes. Same-process notify still
trips the Event immediately; the file is for the other process.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from capitalizator.ops.vault import Vault, write_regular_bytes

WAKE_DIR = "wake"
DESK_STAMP = "desk.stamp"
SIGNER_STAMP = "signer.stamp"
SLICE_S = 0.01


class Wake:
    """In-process notify. `wait` returns True if someone called `notify`."""

    def __init__(self) -> None:
        self._ev = threading.Event()

    def notify(self) -> None:
        self._ev.set()

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout <= 0:
            if self._ev.is_set():
                self._ev.clear()
                return True
            return False
        ok = self._ev.wait(timeout)
        if ok:
            self._ev.clear()
        return ok


class StampWake:
    """Regular-file stamp. Two processes share a path; mtime is the signal."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._ev = threading.Event()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"0")
        self._token = _token(path)

    def notify(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{time.time_ns()}:{os.getpid()}:{os.urandom(8).hex()}".encode()
        write_regular_bytes(self.path, payload)
        self._token = payload
        self._ev.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._take_event() or self._changed():
            return True
        if timeout is not None and timeout <= 0:
            return False
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remain = None if deadline is None else deadline - time.monotonic()
            if remain is not None and remain <= 0:
                return self._changed()
            slice_s = SLICE_S if remain is None else min(SLICE_S, remain)
            if self._ev.wait(slice_s):
                self._ev.clear()
                self._token = _token(self.path)
                return True
            if self._changed():
                return True

    def _take_event(self) -> bool:
        if self._ev.is_set():
            self._ev.clear()
            self._token = _token(self.path)
            return True
        return False

    def _changed(self) -> bool:
        current = _token(self.path)
        if current != self._token:
            self._token = current
            return True
        return False


def _token(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def stamp_path(root: Path, name: str) -> Path:
    return root / WAKE_DIR / name


def desk_wake(vault: Vault) -> StampWake:
    return StampWake(stamp_path(vault.root, DESK_STAMP))


def signer_wake(vault: Vault) -> StampWake:
    return StampWake(stamp_path(vault.root, SIGNER_STAMP))


def desk_wake_from_tape(tape: Path) -> StampWake:
    """`vault.tape` is `root / tape`; the stamp lives next to the layers.

    A bare data_root (tests, pump) is treated as the vault root so the stamp
    does not escape the caller's tree.
    """
    root = tape.parent if tape.name == "tape" else tape
    return StampWake(stamp_path(root, DESK_STAMP))


def idle(
    wake: Wake | StampWake,
    timeout: float,
    *,
    should_stop: Callable[[], bool] | None = None,
    slice_s: float = SLICE_S,
) -> bool:
    """Wait for notify or timeout. Returns True if notified.

    `should_stop` is checked on each slice so SIGTERM is not a full idle_s.
    """
    if timeout <= 0:
        return wake.wait(0)
    end = time.monotonic() + timeout
    while should_stop is None or not should_stop():
        remain = end - time.monotonic()
        if remain <= 0:
            return False
        if wake.wait(min(remain, slice_s)):
            return True
    return False

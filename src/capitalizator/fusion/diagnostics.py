"""Small durable incident journal, independent of the trading SQLite writer."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any


def redact(text: str) -> str:
    # Exception messages may contain HTTP query parameters/headers. Never capture locals.
    text = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:Bearer|Basic)\s+[^\s,\"'}]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)((?:x-bapi-api-key|x-api-key|api[_-]?(?:key|secret|token)|"
        r"authorization|secret|token|password)[\"']?\s*[:=]\s*[\"']?)([^\s,\"'&}\]]+)",
        r"\1[REDACTED]",
        text,
    )
    return re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)


def redact_fields(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_fields(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_fields(item) for item in value]
    return value


class Diagnostics:
    """One runtime owns these files. Failure persistence never depends on SQLite."""

    def __init__(self, root: Path, policy: str) -> None:
        self.directory = root / "logs"
        self.policy = policy
        self.run_id = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.last_failure: dict[str, Any] | None = None
        try:
            saved = json.loads((self.directory / "last_failure.json").read_text())
            if isinstance(saved, dict):
                self.last_failure = saved
        except (OSError, ValueError):
            pass

    def record(self, event: str, **fields: Any) -> None:
        record = {
            "at": time.time(),
            "pid": os.getpid(),
            "run_id": self.run_id,
            "policy": self.policy,
            "event": event,
            **fields,
        }
        record = redact_fields(record)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        # stderr survives an unwritable/full data volume and is collected by Docker.
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except OSError:
            pass
        with self.lock:
            # Cleanup/secondary worker faults must not erase the initiating fault.
            first_failure = event == "failure" and (
                self.last_failure is None or self.last_failure.get("run_id") != self.run_id
            )
            if first_failure:
                self.last_failure = record
            try:
                self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                path = self.directory / "runtime.jsonl"
                if path.exists() and path.stat().st_size >= 5_000_000:
                    for index in (2, 1):
                        old = self.directory / f"runtime.jsonl.{index}"
                        if old.exists():
                            os.replace(old, self.directory / f"runtime.jsonl.{index + 1}")
                    os.replace(path, self.directory / "runtime.jsonl.1")
                fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
                if first_failure:
                    temp = self.directory / ("." + uuid.uuid4().hex)
                    try:
                        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                        with os.fdopen(fd, "w", encoding="utf-8") as stream:
                            stream.write(line)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temp, self.directory / "last_failure.json")
                    finally:
                        temp.unlink(missing_ok=True)
                fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError as exc:
                # Do not replace the original fault with a diagnostic-write error.
                try:
                    print(
                        f"diagnostics_write_failed: {type(exc).__name__}",
                        file=sys.stderr,
                        flush=True,
                    )
                except OSError:
                    pass

    def failure(self, worker: str, exc: BaseException) -> None:
        self.record(
            "failure",
            worker=worker,
            error=f"{type(exc).__name__}: {exc}",
            traceback="".join(traceback.format_exception(exc)),
        )

    def stalled(self, workers: dict[str, Any]) -> None:
        """Capture Python stacks without locals before waiting for trading locks."""
        names = {t.ident: t.name for t in threading.enumerate()}
        self.record(
            "watchdog_stale",
            workers=workers,
            stacks={
                names.get(ident, str(ident)): "".join(traceback.format_stack(frame, limit=30))
                for ident, frame in sys._current_frames().items()
            },
        )

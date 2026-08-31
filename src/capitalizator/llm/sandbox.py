"""Contour B: no sockets, no HTTP. The model (when one exists) never leaves this box."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class SandboxEgress(RuntimeError):
    """HTTP or a TCP connect was attempted from the LLM box."""


@contextmanager
def no_egress() -> Iterator[None]:
    """Fail closed: any TCP connect inside the with-block is an error."""
    original = socket.socket.connect

    def connect(self: socket.socket, *args: Any, **kwargs: Any) -> None:
        raise SandboxEgress("llm sandbox has no egress")

    socket.socket.connect = connect  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original  # type: ignore[method-assign]

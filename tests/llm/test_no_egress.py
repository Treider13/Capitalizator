"""Any TCP connect inside the sandbox is a fail. Summary does not dial out."""

from __future__ import annotations

import socket

import pytest

from capitalizator.llm.daily_summary import DailySummary
from capitalizator.llm.sandbox import SandboxEgress, no_egress


def test_connect_inside_sandbox_is_error() -> None:
    with no_egress(), pytest.raises(SandboxEgress, match="egress"):
        socket.socket().connect(("127.0.0.1", 1))


def test_summary_does_not_open_a_socket() -> None:
    with no_egress():
        out = DailySummary().run("# Карта 2026-08-30\nКасаний нет.")
    assert out["trade_advice"] is False
    assert "Карта" in out["summary"]

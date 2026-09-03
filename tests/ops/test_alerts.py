"""Telegram alerts: one message per change, never per tick, never the token in a note."""

from __future__ import annotations

from pathlib import Path

from capitalizator.ops.alerts import Alerter, send
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_send_reports_status_not_secrets() -> None:
    seen: list[tuple[str, bytes]] = []

    def post(url: str, body: bytes) -> int:
        seen.append((url, body))
        return 200

    ok, note = send("123:SECRET", "42", "привет", post=post)
    assert ok and note == "HTTP 200" and "SECRET" not in note
    assert seen[0][0].endswith("/bot123:SECRET/sendMessage") and b"chat_id=42" in seen[0][1]
    assert send("", "42", "x", post=post) == (False, "telegram not configured")


def test_alerter_fires_on_change_only(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    sent: list[bytes] = []
    al = Alerter("t", "c", post=lambda _u, b: (sent.append(b), 200)[1])
    assert al.on_change(kn, "entries_blocked", [], "clear") is False  # startup, nothing wrong
    assert al.on_change(kn, "entries_blocked", ["no_gateway"], "blocked") is True
    assert al.on_change(kn, "entries_blocked", ["no_gateway"], "blocked") is False  # same → silent
    assert al.on_change(kn, "entries_blocked", [], "released") is True
    assert len(sent) == 2
    assert kn.meta("alerts_last") and "entries_blocked" in kn.meta("alerts_last")
    kn.close()

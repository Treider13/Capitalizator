"""Outgoing Telegram alerts (info / critical). Reading channels stays forbidden.

The signer sends them: it has the network and a 1-second loop, and it is the process
that knows when entries got blocked, a stranger appeared on the venue or the dead-man
fired. The console sends the test message from the Настройки page. Nothing here
decides anything; a failed send is recorded as meta `alerts_last_error` and never
raises into the caller.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from capitalizator.ops.knowledge import Knowledge

API = "https://api.telegram.org/bot{token}/sendMessage"
Poster = Callable[[str, bytes], int]


def _default_post(url: str, body: bytes) -> int:
    req = Request(url, data=body, method="POST")
    with urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed official host
        return int(resp.status)


def send(
    token: str, chat_id: str, text: str, *, post: Poster = _default_post
) -> tuple[bool, str]:
    """(ok, note). The note is the HTTP status or the exception type — never the token."""
    if not token or not chat_id:
        return False, "telegram not configured"
    url = API.format(token=token)
    body = urlencode({"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": "1"})
    try:
        status = post(url, body.encode())
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (URLError, OSError, ValueError) as exc:
        return False, type(exc).__name__
    return 200 <= status < 300, f"HTTP {status}"


class Alerter:
    """Sends a message when a watched fact CHANGES (no repeats every second)."""

    def __init__(self, token: str, chat_id: str, *, post: Poster = _default_post) -> None:
        self.token = token
        self.chat_id = chat_id
        self.post = post
        self._last: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def on_change(self, knowledge: Knowledge, key: str, value: Any, text: str) -> bool:
        """Send `text` when `value` for `key` differs from the last one seen. Returns
        whether a message went out (and was accepted)."""
        stamp = json.dumps(value, sort_keys=True, default=str)
        if self._last.get(key) == stamp:
            return False
        first = key not in self._last
        self._last[key] = stamp
        if first and not value:
            return False  # startup with nothing wrong: no "all clear" spam
        if not self.configured:
            return False
        ok, note = send(self.token, self.chat_id, text, post=self.post)
        if knowledge.available():
            knowledge.set_meta("alerts_last", json.dumps({"key": key, "ok": ok, "note": note}))
            if not ok:
                knowledge.set_meta("alerts_last_error", note)
        return ok

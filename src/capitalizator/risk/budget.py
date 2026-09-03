"""1.7.4 — at most three session intents. The fourth is reject.

Does not place an order. Does not raise size to 'make the count'.
"""

from __future__ import annotations

MAX_SESSION_INTENTS = 3


class SessionBudget:
    def __init__(self, *, max_n: int = MAX_SESSION_INTENTS) -> None:
        # 0 = a closed window (sessions.yaml night / weekend off): every entry refused.
        if max_n < 0:
            raise ValueError("max_n must be >= 0")
        self.max_n = max_n
        self.n = 0

    def allow_entry(self) -> bool:
        return self.n < self.max_n

    def on_intent(self) -> None:
        if not self.allow_entry():
            raise ValueError("session intent cap")
        self.n += 1

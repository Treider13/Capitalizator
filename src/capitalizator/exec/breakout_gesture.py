"""3.13.3 — DEFEND after a puncture is a fake, not a chase.

RETREAT + close beyond is not this skip. Does not open size.
"""

from __future__ import annotations

FAKE_DEFEND = "fake_defend"


def skip_reason(*, gesture: str, close_beyond: bool) -> str | None:
    if gesture == "DEFEND" and close_beyond:
        return FAKE_DEFEND
    return None

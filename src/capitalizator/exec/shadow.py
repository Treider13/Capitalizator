"""4.17.1 paper — same pipeline, mode=shadow, signer is not called.

PHASE-BUILD: G3 must pass before this is a live contour. This module
only records an idea. It does not import signer. It does not send.
"""

from __future__ import annotations

from typing import Any


class ShadowWriter:
    def write(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"mode": "shadow", "sent": False, "payload": payload}

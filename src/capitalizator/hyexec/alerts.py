"""Desk facts for the existing Telegram Alerter. Not a new bot. No advice words."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from capitalizator.ops.knowledge import Knowledge

KINDS = ("harvest", "aplus", "pyramid")

_TEXT = {
    "harvest": "окно сняло часть на +1R {symbol}",
    "aplus": "ступень A+ в overlap {symbol}",
    "pyramid": "вторая нога в плюсе записана {symbol}",
}


def event_text(*, kind: str, symbol: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown hyexec alert: {kind}")
    return _TEXT[kind].format(symbol=symbol)


def stamp(
    knowledge: Knowledge, *, kind: str, symbol: str, at: datetime
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unknown hyexec alert: {kind}")
    row = {"kind": kind, "symbol": symbol, "at": at.isoformat()}
    if knowledge.available():
        knowledge.set_meta("hyexec_event", json.dumps(row, sort_keys=True))
    return row

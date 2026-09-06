"""Public Bybit v5 REST the recorder is allowed to call (no key, read-only).

instruments-info is public: the desk's instrument registry (tick / lot / min
notional / status) must not depend on a signer key being present — without it the
console listed every symbol as "без фактов" and the desk refused them (VPS,
2026-09-03). The recorder publishes the snapshot to knowledge hourly; the signer
does the same when it has a key, and the desk merges whichever is fresher.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from capitalizator.instruments import InstrumentRegistry, instrument_from_bybit
from capitalizator.ops.knowledge import Knowledge

INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"
TESTNET_INSTRUMENTS_URL = "https://api-testnet.bybit.com/v5/market/instruments-info"
Getter = Callable[[str], bytes | str | dict[str, Any]]


def _default_get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "capitalizator-recorder"})
    with urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed https host
        return bytes(resp.read())


def fetch_instruments(
    *, testnet: bool = False, opener: Getter | None = None, category: str = "linear"
) -> list[dict[str, Any]]:
    base = TESTNET_INSTRUMENTS_URL if testnet else INSTRUMENTS_URL
    get = opener or _default_get
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(20):  # 1000 per page; linear has < 20 000 instruments
        params: dict[str, Any] = {"category": category, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        raw = get(f"{base}?{urlencode(params)}")
        if isinstance(raw, dict):
            payload = raw
        else:
            payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        if payload.get("retCode") not in (0, None):
            raise ValueError(
                f"instruments-info retCode {payload.get('retCode')}: {payload.get('retMsg')}"
            )
        result = payload.get("result") or {}
        out.extend(result.get("list") or [])
        cursor = result.get("nextPageCursor") or None
        if not cursor:
            break
    return out


def publish_instruments(
    knowledge: Knowledge,
    *,
    now: datetime | None = None,
    testnet: bool = False,
    opener: Getter | None = None,
) -> int:
    """instruments-info → meta `instruments_snapshot` (same shape the signer writes)."""
    when = now or datetime.now(tz=UTC)
    rows = fetch_instruments(testnet=testnet, opener=opener)
    reg = InstrumentRegistry()
    for row in rows:
        try:
            reg.put(instrument_from_bybit(row, fetched_at=when))
        except ValueError:
            continue
    reg.last_refresh = when
    snap = reg.to_snapshot()
    knowledge.set_meta("instruments_snapshot", json.dumps(snap, sort_keys=True, default=str))
    return len(snap["instruments"])

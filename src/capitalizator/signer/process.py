"""Signer process: SQLite queue in, injected send out. Key never in desk.

Desk writes intent_queue. This process reads pending rows and calls `send`.
Host and key live in Vault / the injected callable — not in this file.
Dead-man (30s) and reconcile (60s) are the existing atoms.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.product import USER_MODES
from capitalizator.signer.deadman import DeadMan
from capitalizator.signer.reconcile import Reconciler
from capitalizator.types import require_utc

SendFn = Callable[[dict[str, Any]], dict[str, Any]]
SENT = frozenset({"sent", "accepted", "ok"})


def drain_once(
    knowledge: Knowledge,
    send: SendFn,
    *,
    user_mode: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Execute pending intents only when the human mode is demo|live."""
    if user_mode not in USER_MODES:
        raise ValueError(f"unknown user_mode: {user_mode!r}")
    require_utc(now)
    if user_mode not in {"demo", "live"}:
        return []
    out: list[dict[str, Any]] = []
    for row in knowledge.pending_intents():
        try:
            result = send(row["payload"])
        except Exception as exc:
            knowledge.mark_intent(row["id"], "failed")
            out.append({"id": row["id"], "status": "failed", "error": str(exc)})
            continue
        status = str(result.get("status") or "")
        marked = "sent" if status in SENT else "failed"
        knowledge.mark_intent(row["id"], marked)
        if marked == "sent":
            knowledge.enqueue_order(
                result,
                created_ts=now.isoformat(),
                intent_id=row["id"],
            )
        out.append({"id": row["id"], "status": marked, "result": result})
    return out


def make_watchdogs(
    *,
    cancel_all: Callable[[], None],
    dead_man_s: int | None = None,
    reconcile_s: int | None = None,
) -> tuple[DeadMan, Reconciler]:
    """30s heartbeat + 60s reconcile. Callbacks are injected."""
    dead = DeadMan(cancel_all, dead_man_s=dead_man_s)
    recon = Reconciler()
    if reconcile_s is not None:
        # interval is documented on the atom; tick cadence is the caller's.
        _ = reconcile_s
    return dead, recon

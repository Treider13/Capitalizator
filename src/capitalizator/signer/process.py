"""Signer process: SQLite queue in, injected send out. Key never in desk.

Desk writes intent_queue. This process reads pending rows and calls `send`.
Host and key live in Vault / the injected callable — not in this file.
Dead-man (30s) and reconcile (60s) are the existing atoms.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.product import USER_MODES
from capitalizator.screener.universe import Universe, load_desk_universe
from capitalizator.signer.deadman import DeadMan
from capitalizator.signer.reconcile import Reconciler
from capitalizator.signer.validate import Signer, UnsignedIntent
from capitalizator.types import require_utc

SendFn = Callable[[dict[str, Any]], dict[str, Any]]
SENT = frozenset({"sent", "accepted", "ok"})
HEARTBEAT_S = 30
RECONCILE_S = 60


def unsigned_from_intent(
    payload: dict[str, Any],
    *,
    trading_mode: str = "testnet",
) -> UnsignedIntent:
    """Map desk Intent dump onto the signer schema. Stop is mandatory."""
    stop = payload.get("stop_px", payload.get("stop"))
    if stop is None:
        raise ValueError("stop must be reduce-only and present")
    qty = payload.get("qty")
    if qty is None:
        qty = "0.001"
    limit = payload.get("limit_px", payload.get("entry"))
    if limit is None:
        raise ValueError("limit/entry required")
    tp = payload.get("tp_px", payload.get("tp"))
    return UnsignedIntent(
        symbol=str(payload["symbol"]),
        side=payload["side"],
        qty=Decimal(str(qty)),
        limit_px=Decimal(str(limit)),
        stop_px=Decimal(str(stop)),
        tp_px=None if tp is None else Decimal(str(tp)),
        reduce_only_stop=bool(payload.get("reduce_only_stop", True)),
        trading_mode=trading_mode,  # type: ignore[arg-type]
    )


def validate_queue_payload(
    payload: dict[str, Any],
    *,
    universe: Universe | None = None,
) -> dict[str, Any]:
    """Desk 24-symbol universe. week0 stays the isolated Signer() default."""
    raw = unsigned_from_intent(payload)
    order = Signer(universe=universe or load_desk_universe()).validate(raw)
    return order.model_dump(mode="json")


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


def on_signer_exit(cancel_all: Callable[[], None]) -> None:
    """Supervisor hook: process gone → cancel_all. No leftover live order."""
    cancel_all()


def make_watchdogs(
    *,
    cancel_all: Callable[[], None],
    dead_man_s: int | None = None,
    reconcile_s: int | None = None,
) -> tuple[DeadMan, Reconciler]:
    """30s heartbeat + 60s reconcile. Callbacks are injected."""
    dead = DeadMan(cancel_all, dead_man_s=dead_man_s or HEARTBEAT_S)
    recon = Reconciler()
    if reconcile_s is not None:
        _ = reconcile_s
    return dead, recon


def drain_validated(
    knowledge: Knowledge,
    send: SendFn,
    *,
    user_mode: str,
    now: datetime,
    universe: Universe | None = None,
) -> list[dict[str, Any]]:
    """Drain pending intents after Signer.validate. Key stays in `send`."""

    def checked(payload: dict[str, Any]) -> dict[str, Any]:
        signed = validate_queue_payload(payload, universe=universe)
        return send(signed)

    return drain_once(knowledge, checked, user_mode=user_mode, now=now)

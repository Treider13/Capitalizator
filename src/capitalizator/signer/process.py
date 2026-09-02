"""Signer process: SQLite queue in, injected send out. Key never in desk.

Desk writes intent_queue. This process reads pending rows and calls `send`.
Host and key live in Vault / the injected callable — not in this file.
Dead-man (30s) and reconcile (60s) are the existing atoms.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from time import sleep as _sleep
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
    allow_default_qty: bool = True,
) -> UnsignedIntent:
    """Map desk Intent dump onto the signer schema. Stop is mandatory.

    `allow_default_qty=False` (the live drain) refuses an unsized intent: the
    desk sizes every intent from equity (D-11); "0.001 anyway" is a fixture, not
    a position.
    """
    stop = payload.get("stop_px", payload.get("stop"))
    if stop is None:
        raise ValueError("stop must be reduce-only and present")
    qty = payload.get("qty")
    if qty is None:
        if not allow_default_qty:
            raise ValueError("intent not sized: qty missing (desk sizing did not run)")
        qty = "0.001"
    raw_mult = payload["size_mult"] if "size_mult" in payload else "1"
    if raw_mult is None:
        raw_mult = "1"
    mult = Decimal(str(raw_mult))
    if mult <= 0:
        raise ValueError("size_mult must be > 0")
    qty = Decimal(str(qty)) * mult
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
    raw = unsigned_from_intent(payload, allow_default_qty=False)
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
            # The queue row id is the intent's identity: two intents with identical
            # content (same zone on two days) must not share an orderLinkId.
            result = send({**row["payload"], "intent_id": row["id"]})
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


def serve_loop(
    *,
    knowledge: Knowledge,
    vault: Any,
    send: SendFn,
    cancel_all: Callable[[], None],
    should_stop: Callable[[], bool],
    idle_s: float = 1.0,
    now: datetime | None = None,
    sleep: Callable[[float], None] = _sleep,
) -> None:
    """No-key loop: drain intent_queue through `send`, watch the DESK heartbeat.

    The old DeadMan beat and ticked itself in one iteration and could never fire
    (Н-4). The Watchdog reads the desk heartbeat the desk writes every tick; a
    silent desk calls `cancel_all` once per episode and blocks the drain.
    """
    from capitalizator.gateway.watchdog import Watchdog
    from capitalizator.ops.product import read_user_mode

    dead = Watchdog(dead_man_s=HEARTBEAT_S, cancel_entries=lambda _reason: cancel_all())
    _legacy_dead, recon = make_watchdogs(cancel_all=cancel_all)
    last_recon: datetime | None = None
    while not should_stop():
        when = now if now is not None else datetime.now(tz=UTC)
        require_utc(when)
        mode = read_user_mode(vault)
        hb = knowledge.meta("desk_heartbeat")
        if hb:
            try:
                dead.beat("desk", datetime.fromisoformat(hb))
            except ValueError:
                pass
        stale = dead.check(when)
        knowledge.set_meta("entries_blocked", json.dumps(sorted(stale)))
        if mode in {"demo", "live"} and not stale:
            drain_validated(knowledge, send, user_mode=mode, now=when)
        if last_recon is None or (when - last_recon).total_seconds() >= RECONCILE_S:
            recon.tick({})
            last_recon = when
        if idle_s:
            sleep(idle_s)


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
        # Keep the desk fields the gateway needs (idempotency, staleness, leverage).
        for key in ("valid_until", "lev", "touch_id", "intent_id", "risk_config_id", "tag"):
            if key in payload and key not in signed:
                signed[key] = payload[key]
        return send(signed)

    return drain_once(knowledge, checked, user_mode=user_mode, now=now)


# --- gateway-driven serve loop (W4b) ------------------------------------------------------
MODE_FOR_GATEWAY = {"demo": {"testnet"}, "live": {"live_sub", "live_main"}}


def gateway_mode_ok(user_mode: str, gateway_mode: str) -> bool:
    """demo talks to testnet only; live to a live key only. Never cross."""
    return gateway_mode in MODE_FOR_GATEWAY.get(user_mode, set())


def drain_oms(knowledge: Knowledge, gateway: Any, *, now: datetime) -> list[dict[str, Any]]:
    """Execute desk decisions (stop moves, trailing, half TP, flatten) on the venue."""
    out: list[dict[str, Any]] = []
    for cmd in knowledge.pending_oms():
        kind, symbol, p = cmd["kind"], cmd["symbol"], cmd["payload"]
        try:
            if kind == "amend_stop":
                res = gateway.amend_stop(symbol, Decimal(str(p["stop"])))
            elif kind == "set_trailing":
                active = p.get("active_price")
                res = gateway.set_trailing(
                    symbol,
                    Decimal(str(p["distance"])),
                    None if active is None else Decimal(str(active)),
                )
            elif kind == "half_tp":
                res = gateway.place_half_tp(
                    symbol=symbol,
                    side=str(p["side"]),
                    qty=Decimal(str(p["qty"])),
                    price=Decimal(str(p["price"])),
                    link=str(p.get("paper_id") or p.get("touch_id") or symbol),
                )
            elif kind == "flatten":
                res = gateway.flatten(symbol, reason=str(p.get("reason") or "oms"))
            elif kind == "cancel_entries":
                res = gateway.cancel_entries(symbol, reason=str(p.get("reason") or "oms"))
            else:
                knowledge.mark_oms(cmd["id"], "skipped", {"error": f"unknown kind {kind}"})
                continue
            knowledge.mark_oms(cmd["id"], "done", res if isinstance(res, dict) else {"result": res})
            out.append({"id": cmd["id"], "kind": kind, "status": "done"})
        except Exception as exc:
            knowledge.mark_oms(cmd["id"], "failed", {"error": str(exc)})
            out.append({"id": cmd["id"], "kind": kind, "status": "failed", "error": str(exc)})
    return out


def publish_exchange_state(
    knowledge: Knowledge, gateway: Any, tracker: Any, *, now: datetime
) -> dict[str, Any]:
    """REST truth every reconcile tick: equity, positions, mismatches → meta for the UI."""
    snap: dict[str, Any] = {"at": now.isoformat(), "mode": gateway.mode}
    try:
        snap["equity"] = str(gateway.wallet_equity())
    except Exception as exc:
        snap["equity_error"] = str(exc)
    try:
        rest = gateway.positions()
        expected: set[str] = set()
        raw_acct = knowledge.meta("account")
        if raw_acct:
            try:
                expected = {str(o["symbol"]) for o in json.loads(raw_acct).get("open", [])}
            except (ValueError, KeyError, TypeError):
                expected = set()
        mismatches = tracker.reconcile(rest, now=now, expected=expected)
        snap["positions"] = [tracker.positions[s].to_payload() for s in tracker.open_symbols()]
        snap["mismatches"] = mismatches
        snap["stop_missing"] = [
            s for s in tracker.open_symbols() if not tracker.stop_confirmed(s)
        ]
    except Exception as exc:
        snap["positions_error"] = str(exc)
    knowledge.set_meta("exchange_state", json.dumps(snap, sort_keys=True, default=str))
    return snap


INSTRUMENTS_REFRESH_S = 3600


def publish_instruments(knowledge: Knowledge, gateway: Any, *, now: datetime) -> int:
    """instruments-info from the venue → meta for the desk's InstrumentRegistry (D-04)."""
    from capitalizator.instruments import InstrumentRegistry, instrument_from_bybit

    rows = gateway.instruments()
    reg = InstrumentRegistry()
    for row in rows:
        try:
            reg.put(instrument_from_bybit(row, fetched_at=now))
        except ValueError:
            continue
    reg.last_refresh = now
    snap = reg.to_snapshot()
    knowledge.set_meta("instruments_snapshot", json.dumps(snap, sort_keys=True, default=str))
    return len(snap["instruments"])


def serve_gateway_loop(
    *,
    knowledge: Knowledge,
    vault: Any,
    gateway: Any,
    tracker: Any,
    feed: Any | None,
    should_stop: Callable[[], bool],
    idle_s: float = 1.0,
    now: datetime | None = None,
    sleep: Callable[[float], None] = _sleep,
    dead_man_s: int | None = None,
    reconcile_s: int | None = None,
) -> None:
    """Real signer loop: watchdog, intent drain via the gateway, OMS drain, reconcile.

    Blocks new entries (not stops) when: desk heartbeat silent, private WS silent,
    reconcile mismatch, or a position without a confirmed stop on the venue.
    """
    from capitalizator.gateway.watchdog import Watchdog
    from capitalizator.ops.product import read_user_mode

    dead = Watchdog(
        dead_man_s=dead_man_s or HEARTBEAT_S,
        cancel_entries=lambda reason: gateway.cancel_entries(None, reason=reason),
    )
    recon_every = reconcile_s or RECONCILE_S
    last_recon: datetime | None = None
    last_instruments: datetime | None = None
    if feed is not None:
        feed.start()
    while not should_stop():
        when = now if now is not None else datetime.now(tz=UTC)
        require_utc(when)
        mode = read_user_mode(vault)
        due = (
            last_instruments is None
            or (when - last_instruments).total_seconds() >= INSTRUMENTS_REFRESH_S
        )
        if due:
            try:
                publish_instruments(knowledge, gateway, now=when)
            except Exception as exc:  # venue/network: keep the last snapshot, say why
                knowledge.set_meta("instruments_error", str(exc))
            last_instruments = when
        if feed is not None:
            feed.drain(now=when)
            if feed.last_frame_at is not None:
                dead.beat("ws_private", feed.last_frame_at)
        hb = knowledge.meta("desk_heartbeat")
        if hb:
            try:
                dead.beat("desk", datetime.fromisoformat(hb))
            except ValueError:
                pass
        stale = dead.check(when)
        blocked: list[str] = list(stale)
        if last_recon is None or (when - last_recon).total_seconds() >= recon_every:
            state = publish_exchange_state(knowledge, gateway, tracker, now=when)
            if state.get("mismatches"):
                blocked.append("reconcile_mismatch")
            if state.get("stop_missing"):
                blocked.append("stop_missing:" + ",".join(state["stop_missing"]))
            last_recon = when
        knowledge.set_meta("entries_blocked", json.dumps(sorted(blocked)))
        if mode in {"demo", "live"} and gateway_mode_ok(mode, gateway.mode):
            # OMS first: protecting an open position beats opening a new one.
            drain_oms(knowledge, gateway, now=when)
            if not blocked:
                drain_validated(knowledge, gateway.send, user_mode=mode, now=when)
        if idle_s:
            sleep(idle_s)

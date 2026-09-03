"""Signer process: SQLite queue in, injected send out. Key never in desk.

Desk writes intent_queue. This process reads pending rows and calls `send`.
Host and key live in Vault / the injected callable — not in this file.

Statuses the gateway returns and what the signer persists:
  sent       → `sent`      (+ order_queue row)
  rejected   → `rejected`  (venue or local refusal; the desk frees the idea)
  unknown    → `unknown`   (transport failed after the order left; resolved by link)
  no_gateway → `no_gateway` (no key/process; the desk keeps the idea, row re-sent later)
Anything else is a bug and is persisted as `failed`.

Entry blocking is *sticky*: a reconcile mismatch, a missing venue stop or an
unknown venue position blocks new entries until an operator posts
`release_signer` (audit B1: the old block lasted one loop iteration).
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
from capitalizator.risk.session import load_time_config
from capitalizator.screener.universe import Universe, load_desk_universe
from capitalizator.signer.validate import Signer, UnsignedIntent
from capitalizator.types import require_utc

SendFn = Callable[[dict[str, Any]], dict[str, Any]]
SENT = frozenset({"sent", "accepted", "ok"})
PERSISTED = frozenset({"sent", "rejected", "unknown", "no_gateway"})


def _clock_from_yaml() -> tuple[int, int]:
    """dead_man_s / reconcile_s from infra/time.yaml — one source, not module magic."""
    cfg = load_time_config()
    dead = int(cfg["dead_man_s"])
    recon = int(cfg["reconcile_s"])
    if dead <= 0 or recon <= 0:
        raise ValueError("dead_man_s / reconcile_s must be > 0")
    return dead, recon


HEARTBEAT_S, RECONCILE_S = _clock_from_yaml()


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
            knowledge.mark_intent(row["id"], "failed", {"error": str(exc)})
            out.append({"id": row["id"], "status": "failed", "error": str(exc)})
            continue
        status = str(result.get("status") or "")
        if status in SENT:
            marked = "sent"
        elif status in PERSISTED:
            marked = status
        else:
            marked = "failed"
        knowledge.mark_intent(row["id"], marked, result)
        if marked == "sent":
            knowledge.enqueue_order(
                result,
                created_ts=now.isoformat(),
                intent_id=row["id"],
            )
        out.append({"id": row["id"], "status": marked, "result": result})
    return out


def resolve_unknown_intents(
    knowledge: Knowledge, gateway: Any, *, now: datetime
) -> list[dict[str, Any]]:
    """Rows whose transport failed after the order left: ask the venue by link id."""
    out: list[dict[str, Any]] = []
    for row in knowledge.intents_with_status("unknown"):
        res = row.get("result") or {}
        link = str(res.get("orderLinkId") or "")
        symbol = str(row["payload"].get("symbol") or res.get("symbol") or "")
        if not link or not symbol:
            knowledge.mark_intent(row["id"], "failed", {"error": "unknown without link"})
            continue
        verdict = gateway.resolve_unknown(symbol, link)
        status = str(verdict.get("status") or "unknown")
        if status == "unknown":
            out.append({"id": row["id"], "status": "unknown"})
            continue
        knowledge.mark_intent(row["id"], status, verdict)
        if status == "sent":
            knowledge.enqueue_order(verdict, created_ts=now.isoformat(), intent_id=row["id"])
        out.append({"id": row["id"], "status": status})
    return out


def requeue_no_gateway(knowledge: Knowledge) -> int:
    """A gateway appeared: rows parked as `no_gateway` become pending again."""
    n = 0
    for row in knowledge.intents_with_status("no_gateway"):
        knowledge.mark_intent(row["id"], "pending")
        n += 1
    return n


def on_signer_exit(cancel_all: Callable[[], None]) -> None:
    """Supervisor hook: process gone → cancel_all. No leftover live order."""
    cancel_all()


def serve_loop(
    *,
    knowledge: Knowledge,
    vault: Any,
    should_stop: Callable[[], bool],
    idle_s: float = 1.0,
    now: datetime | None = None,
    sleep: Callable[[float], None] = _sleep,
    dead_man_s: int | None = None,
) -> None:
    """No-key loop. Nothing can be sent, so nothing pretends to be: pending intents
    are parked as `no_gateway` (the desk keeps the idea; `requeue_no_gateway` brings
    them back when a key appears). The desk heartbeat is still watched and
    reported, but there are no venue orders to cancel."""
    from capitalizator.gateway.watchdog import Watchdog
    from capitalizator.ops.product import read_user_mode

    dead = Watchdog(dead_man_s=dead_man_s or HEARTBEAT_S, cancel_entries=lambda _reason: None)
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
        knowledge.set_meta("entries_blocked", json.dumps(sorted(stale + ["no_gateway"])))
        if mode in {"demo", "live"}:
            drain_once(knowledge, park_no_gateway, user_mode=mode, now=when)
        knowledge.set_meta("signer_heartbeat", when.isoformat())
        if idle_s:
            sleep(idle_s)


def park_no_gateway(row: dict[str, Any]) -> dict[str, Any]:
    """The no-key `send`: an honest status, not a fake refusal."""
    return {"status": "no_gateway", "symbol": row.get("symbol")}


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
        snap["unknown_positions"] = tracker.unknown_symbols()
        snap["unknown_detail"] = [
            tracker.unknown[s].to_payload() for s in tracker.unknown_symbols()
        ]
        snap["stop_missing"] = [
            s for s in tracker.open_symbols() if not tracker.stop_confirmed(s)
        ]
        snap["fills"] = [
            {
                "symbol": f.symbol, "side": f.side, "price": str(f.price), "qty": str(f.qty),
                "fee": str(f.fee), "orderLinkId": f.order_link_id,
                "exec_time": f.exec_time.isoformat() if f.exec_time else None,
                "is_maker": f.is_maker,
            }
            for f in tracker.fills[-200:]
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

    Blocks new entries (never stops or exits) when:
      * the desk heartbeat is silent, the private socket is down, or the REST
        reconcile has not succeeded within dead_man_s (watchdog, per episode);
      * a reconcile reported a mismatch / an unknown venue position / a position
        without a confirmed venue stop — **sticky** until an operator posts
        `release_signer` (with ack) — audit B1;
      * the process just started: the first reconcile runs before the first drain.
    """
    from capitalizator.gateway.watchdog import Watchdog
    from capitalizator.ops.product import read_user_mode

    dead = Watchdog(
        dead_man_s=dead_man_s or HEARTBEAT_S,
        cancel_entries=lambda reason: _cancel_entries_safely(knowledge, gateway, reason),
    )
    recon_every = reconcile_s or RECONCILE_S
    last_recon: datetime | None = None
    last_instruments: datetime | None = None
    # reason → first seen (iso). Persisted: a signer restart must not clear a block
    # an operator has not released.
    sticky: dict[str, str] = {}
    raw_sticky = knowledge.meta("entries_blocked_since")
    if raw_sticky:
        try:
            loaded = json.loads(raw_sticky)
            if isinstance(loaded, dict):
                sticky = {str(k): str(v) for k, v in loaded.items()}
        except json.JSONDecodeError:
            sticky = {}
    if feed is not None:
        feed.start()
    requeued = requeue_no_gateway(knowledge)
    if requeued:
        knowledge.set_meta("signer_requeued", str(requeued))
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
        # --- operator commands addressed to the signer -------------------------
        for cmd in knowledge.claim_commands(("release_signer", "ack_position")):
            try:
                if cmd["kind"] == "release_signer":
                    released = sorted(sticky)
                    sticky.clear()
                    knowledge.mark_command(cmd["id"], "done", {"released": released})
                else:
                    sym = str(cmd["payload"].get("symbol") or "")
                    ok = tracker.acknowledge(sym)
                    knowledge.mark_command(cmd["id"], "done", {"acknowledged": ok, "symbol": sym})
            except Exception as exc:
                knowledge.mark_command(cmd["id"], "failed", {"error": str(exc)})
        # --- liveness ------------------------------------------------------------
        if feed is not None:
            feed.drain(now=when)
            connected = feed.connected()
            if connected:
                dead.beat("ws_private", when)
            elif connected is None and feed.last_frame_at is not None:
                dead.beat("ws_private", feed.last_frame_at)
        hb = knowledge.meta("desk_heartbeat")
        if hb:
            try:
                dead.beat("desk", datetime.fromisoformat(hb))
            except ValueError:
                pass
        # --- REST truth ------------------------------------------------------------
        if last_recon is None or (when - last_recon).total_seconds() >= recon_every:
            state = publish_exchange_state(knowledge, gateway, tracker, now=when)
            if "positions_error" not in state:
                dead.beat("rest", when)
            if state.get("mismatches"):
                sticky.setdefault("reconcile_mismatch", when.isoformat())
            if state.get("unknown_positions"):
                sticky.setdefault(
                    "unknown_position:" + ",".join(state["unknown_positions"]), when.isoformat()
                )
            if state.get("stop_missing"):
                sticky.setdefault(
                    "stop_missing:" + ",".join(state["stop_missing"]), when.isoformat()
                )
            resolve_unknown_intents(knowledge, gateway, now=when)
            last_recon = when
        stale = dead.check(when)
        blocked = sorted(set(stale) | set(sticky))
        knowledge.set_meta("entries_blocked", json.dumps(blocked))
        knowledge.set_meta("entries_blocked_since", json.dumps(sticky, sort_keys=True))
        knowledge.set_meta("signer_heartbeat", when.isoformat())
        if mode in {"demo", "live"} and gateway_mode_ok(mode, gateway.mode):
            # OMS first: protecting an open position beats opening a new one.
            drain_oms(knowledge, gateway, now=when)
            if not blocked:
                drain_validated(knowledge, gateway.send, user_mode=mode, now=when)
        if idle_s:
            sleep(idle_s)


def _cancel_entries_safely(knowledge: Knowledge, gateway: Any, reason: str) -> None:
    """Watchdog callback: cancel entry orders; a venue error is recorded, not raised."""
    try:
        gateway.cancel_entries(None, reason=reason)
        knowledge.set_meta("dead_man_last", json.dumps({"reason": reason, "ok": True}))
    except Exception as exc:
        knowledge.set_meta(
            "dead_man_last", json.dumps({"reason": reason, "ok": False, "error": str(exc)})
        )

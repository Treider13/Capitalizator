"""One exchange writer, durable outbox and reconciliation-first recovery."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from capitalizator.fusion.config import Config
from capitalizator.fusion.exchange import VenueError
from capitalizator.fusion.risk import ACTIVE, floor_step
from capitalizator.fusion.store import Store, encode

STATUS = {
    "New": "accepted",
    "Untriggered": "accepted",
    "PartiallyFilled": "partial",
    "Filled": "filled",
    "Cancelled": "cancelled",
    "Rejected": "rejected",
    "PartiallyFilledCanceled": "cancelled",
    "Deactivated": "cancelled",
}


class Executor:
    def __init__(
        self,
        store: Store,
        api: Any,
        config: Config,
        *,
        entry_lock: Any = None,
        authorize: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.store, self.api, self.config = store, api, config
        self.mode = api.mode
        self.instruments = api.instruments()
        self.positions: list[dict[str, Any]] = []
        self.last_reconcile = 0.0
        self.last_error = ""
        self.day_halted = False
        self.entry_lock = entry_lock if entry_lock is not None else nullcontext()
        self.authorize = authorize
        self.position_versions: dict[tuple[str, int], float] = {}
        # Sending was persisted before the network call; a crash makes it unknown.
        with store.transaction() as db:
            db.execute(
                "UPDATE orders SET state='unknown' WHERE mode=? AND state='sending'", (self.mode,)
            )
            db.execute(
                "UPDATE commands SET state='pending' WHERE mode=? AND state='sending'", (self.mode,)
            )

    def set_state(self, ident: str, state: str, at: float, error: str = "") -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orders SET state=?,updated=?,error=? WHERE id=? AND mode=?",
                (state, at, error, ident, self.mode),
            )

    def private(self, frame: dict[str, Any], at: float) -> None:
        topic = str(frame.get("topic") or "")
        for row in frame.get("data") or []:
            if topic.startswith("position"):
                key = (str(row["symbol"]), int(row.get("positionIdx") or 0))
                updated = float(row.get("updatedTime") or at * 1000)
                size = float(row.get("size") or 0)
                if not math.isfinite(updated) or not math.isfinite(size) or size < 0:
                    raise ValueError("invalid private position")
                if updated < self.position_versions.get(key, 0):
                    continue
                self.position_versions[key] = updated
                self.positions = [
                    p
                    for p in self.positions
                    if (p["symbol"], int(p.get("positionIdx") or 0)) != key
                ]
                if size > 0:
                    self.positions.append(dict(row))
                with self.store.transaction() as db:
                    account = db.execute(
                        "SELECT body FROM account WHERE mode=?", (self.mode,)
                    ).fetchone()
                    if account:
                        body = json.loads(account["body"])
                        body["positions"] = self.positions
                        body["positions_at"] = at
                        # A position notification does not refresh wallet freshness.
                        db.execute(
                            "UPDATE account SET body=? WHERE mode=?", (encode(body), self.mode)
                        )
            elif topic.startswith("execution"):
                self.store.execution(self.mode, row)
            elif topic.startswith("order"):
                ident = str(row.get("orderLinkId") or "")
                if ident.startswith("acr-") and row.get("orderStatus") in STATUS:
                    # REST reconciliation is authoritative for reversals/races; a late
                    # New notification must not turn Filled back into accepted.
                    existing = self.store.rows(
                        "SELECT state FROM orders WHERE id=? AND mode=?", (ident, self.mode)
                    )
                    state = STATUS[row["orderStatus"]]
                    if existing:
                        old = existing[0]["state"]
                        advances = (
                            old not in {"closed", "filled"}
                            and not (
                                state == "accepted"
                                and old in {"partial", "cancelling", "cancelled", "rejected"}
                            )
                            and not (state == "partial" and old in {"cancelled", "rejected"})
                        )
                        if advances:
                            self.set_state(ident, state, at)

    def reconcile(self, at: float) -> None:
        equity, positions, orders = self.api.account()
        prior = {(p["symbol"], int(p.get("positionIdx") or 0)): p for p in self.positions}
        positions = [
            prior[key]
            if key in prior
            and p.get("updatedTime")
            and float(p["updatedTime"]) < self.position_versions.get(key, 0)
            else p
            for p in positions
            for key in [(p["symbol"], int(p.get("positionIdx") or 0))]
        ]
        cursor = float(self.store.meta("execution_cursor:" + self.mode, at - 3600))
        # Bybit history query is bounded to seven days. Page every interval on restart.
        while cursor < at:
            end = min(at, cursor + 6 * 86400)
            for execution in self.api.executions(int(max(0, cursor - 60) * 1000), int(end * 1000)):
                self.store.execution(self.mode, execution)
            cursor = end
            self.store.put_meta("execution_cursor:" + self.mode, cursor)
        self.positions = [p for p in positions if float(p.get("size") or 0) > 0]
        for p in positions:
            key = (str(p["symbol"]), int(p.get("positionIdx") or 0))
            self.position_versions[key] = max(
                self.position_versions.get(key, 0), float(p.get("updatedTime") or 0)
            )
        self.store.account(
            self.mode,
            at,
            equity,
            self.positions,
            orders,
            str(datetime.fromtimestamp(at, UTC).date()),
        )
        account = self.store.rows("SELECT * FROM account WHERE mode=?", (self.mode,))[0]
        self.day_halted = equity <= account["day_start"] * (1 - self.config.day_loss_fraction)
        open_by_id = {r.get("orderLinkId"): r for r in orders}
        active = self.store.rows(
            "SELECT * FROM orders WHERE mode=? AND state IN "
            "('pending','sending','unknown','accepted','partial','filled','cancelling')",
            (self.mode,),
        )
        for row in active:
            if row["state"] == "pending":
                continue
            venue = open_by_id.get(row["id"]) or self.api.lookup(row["symbol"], row["id"])
            if venue:
                state = STATUS.get(venue["orderStatus"], "unknown")
                if state == "filled" and not any(
                    p["symbol"] == row["symbol"] for p in self.positions
                ):
                    # Require two consecutive reconciliations with no position.
                    if row["error"] == "flat_observed":
                        state = "closed"
                    else:
                        self.set_state(row["id"], "filled", at, "flat_observed")
                        continue
                self.set_state(row["id"], state, at)
            elif row["state"] in {"unknown", "sending"}:
                # An empty lookup does not prove a timed-out send was rejected.
                self.set_state(row["id"], "unknown", at, "lookup_empty")
            elif row["state"] != "filled":
                self.set_state(row["id"], "unknown", at, "venue_order_unresolved")
        self.last_reconcile = at
        self.last_error = ""
        self._protect(at)

    def _protect(self, at: float) -> None:
        for pos in self.positions:
            rows = self.store.rows(
                "SELECT * FROM orders WHERE mode=? AND symbol=? ORDER BY created DESC LIMIT 1",
                (self.mode, pos["symbol"]),
            )
            if not rows or rows[0]["state"] in {"closed", "rejected"}:
                self.store.put_meta("unmanaged_position", {"symbol": pos["symbol"], "at": at})
                continue
            body = json.loads(rows[0]["body"])
            if self.day_halted:
                self.store.command(
                    "day-halt-" + rows[0]["id"],
                    self.mode,
                    pos["symbol"],
                    "flatten",
                    at,
                    {"reason": "daily_loss_limit"},
                )
            contracts = self.store.rows(
                "SELECT state FROM contracts WHERE id=?", (rows[0]["contract"],)
            )
            if not contracts or contracts[0]["state"] != "confirmed":
                self.store.command(
                    "invalid-contract-" + rows[0]["id"],
                    self.mode,
                    pos["symbol"],
                    "flatten",
                    at,
                    {"reason": "fill_after_contract_invalidation"},
                )
            stop = float(pos.get("stopLoss") or 0)
            if stop <= 0:
                attempted = self.store.meta("stop_attempt:" + rows[0]["id"])
                if attempted is not None:
                    self.store.command(
                        "stop-unconfirmed-" + rows[0]["id"],
                        self.mode,
                        pos["symbol"],
                        "flatten",
                        at,
                        {"reason": "stop_not_confirmed_after_reconcile"},
                    )
                    continue
                try:
                    self.store.put_meta("stop_attempt:" + rows[0]["id"], at)
                    self.api.stop(pos["symbol"], float(body["stop"]))
                except Exception:
                    self.store.command(
                        "stop-failed-" + rows[0]["id"],
                        self.mode,
                        pos["symbol"],
                        "flatten",
                        at,
                        {"reason": "stop_not_confirmed"},
                    )
                continue
            mark = float(pos.get("markPrice") or pos.get("avgPrice") or 0)
            liq = float(pos.get("liqPrice") or 0)
            invalid = (pos["side"] == "Buy" and liq > 0 and stop <= liq) or (
                pos["side"] == "Sell" and liq > 0 and stop >= liq
            )
            if invalid or at - rows[0]["created"] >= self.config.max_hold_s:
                self.store.command(
                    "risk-exit-" + rows[0]["id"],
                    self.mode,
                    pos["symbol"],
                    "flatten",
                    at,
                    {"reason": "liquidation_or_time_limit"},
                )
            target = float(body["target"])
            if mark and (
                (pos["side"] == "Buy" and mark >= target)
                or (pos["side"] == "Sell" and mark <= target)
            ):
                self.store.command(
                    "target-" + rows[0]["id"],
                    self.mode,
                    pos["symbol"],
                    "flatten",
                    at,
                    {"reason": "structural_target"},
                )

    def tick(self, at: float, allow_entries: bool) -> None:
        if at - self.last_reconcile >= self.config.reconcile_s:
            self.reconcile(at)
        allow_entries = allow_entries and not self.day_halted
        # Bounded control batch followed by bounded entry batch prevents starvation.
        errors = []
        for command in self.store.rows(
            "SELECT c.* FROM commands c LEFT JOIN dispatch d "
            "ON d.kind='command' AND d.id=c.id WHERE c.mode=? "
            "AND c.state='pending' AND COALESCE(d.next_at,0)<=? ORDER BY "
            "COALESCE(d.attempted,c.at), CASE WHEN c.kind='flatten' THEN 0 ELSE 1 END,"
            "c.at,c.id LIMIT 16",
            (self.mode, at),
        ):
            self._dispatch("command", command["id"], at, at)
            try:
                self._command(command, at)
            except Exception as exc:
                # Persist the retry budget but let other symbols receive protection.
                self._dispatch(
                    "command", command["id"], at, at + self.config.reconcile_s, type(exc).__name__
                )
                errors.append(exc)
        if errors:
            # Caller reports degraded broker health. No entries after failed protection.
            raise errors[0]
        rows = self.store.rows(
            "SELECT o.* FROM orders o LEFT JOIN dispatch d "
            "ON d.kind='cancel' AND d.id=o.id LEFT JOIN contracts c ON c.id=o.contract "
            "WHERE o.mode=? AND o.state IN "
            "('pending','accepted','partial','cancelling','unknown') "
            "AND (o.state='pending' OR ?=0 OR o.expires<=? "
            "OR c.state IS NULL OR c.state<>'confirmed') "
            "AND (o.state='pending' OR COALESCE(d.next_at,0)<=?) "
            "ORDER BY o.created,o.id LIMIT 16",
            (self.mode, int(allow_entries), at, at),
        )
        for row in rows:
            definition = self.store.rows(
                "SELECT state FROM contracts WHERE id=?", (row["contract"],)
            )
            valid = definition and definition[0]["state"] == "confirmed" and at < row["expires"]
            if row["state"] == "pending":
                if not valid or not allow_entries:
                    self.set_state(row["id"], "cancelled", at, "authorization_expired")
                    continue
                # Pause acknowledgement and send authorization share one lock.
                # No market-state lock is held across network I/O.
                with self.entry_lock:
                    if self.authorize is not None and not self.authorize(row):
                        self.set_state(row["id"], "cancelled", at, "authorization_revoked")
                        continue
                    self.set_state(row["id"], "sending", at)
                    try:
                        result = self.api.place(json.loads(row["body"]))
                    except VenueError as exc:
                        self.set_state(
                            row["id"],
                            "unknown"
                            if exc.code in {10000, 10016, 10019, 110072, 20006}
                            else "rejected",
                            at,
                            str(exc),
                        )
                    except Exception as exc:
                        self.set_state(row["id"], "unknown", at, type(exc).__name__)
                    else:
                        with self.store.transaction() as db:
                            db.execute(
                                "UPDATE orders SET state='accepted',venue_id=?,updated=? "
                                "WHERE id=?",
                                (result.get("orderId"), at, row["id"]),
                            )
            elif not valid or not allow_entries:
                self._cancel(row, at)

    def _dispatch(self, kind: str, ident: str, at: float, next_at: float, error: str = "") -> None:
        with self.store.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO dispatch VALUES(?,?,?,?,?)",
                (kind, ident, at, next_at, error),
            )

    def _cancel(self, row: dict[str, Any], at: float) -> None:
        sent = self.store.rows(
            "SELECT next_at FROM dispatch WHERE kind='cancel' AND id=?", (row["id"],)
        )
        if sent and at < sent[0]["next_at"]:
            return
        # Acknowledgement is asynchronous. Retry only at reconciliation cadence,
        # including after restart/timeout; private queue traffic cannot amplify writes.
        self._dispatch("cancel", row["id"], at, at + self.config.reconcile_s)
        self.api.cancel(row["symbol"], row["id"])
        if row["state"] != "unknown":
            self.set_state(row["id"], "cancelling", at)

    def _command(self, command: dict[str, Any], at: float) -> None:
        kind, symbol = command["kind"], command["symbol"]
        body = json.loads(command["body"])
        if kind == "flatten":
            pending = self.store.rows(
                "SELECT id,state,symbol FROM orders WHERE mode=? AND symbol=?", (self.mode, symbol)
            )
            for row in pending:
                if row["state"] in ACTIVE and row["state"] != "filled":
                    if row["state"] == "pending":
                        self.set_state(row["id"], "cancelled", at)
                    else:
                        self._cancel(row, at)
            # Re-read actual position; a paper fill never supplies this quantity.
            _, positions, _ = self.api.account()
            positions = [
                p for p in positions if p["symbol"] == symbol and float(p.get("size") or 0)
            ]
            for pos in positions:
                ident = body.get("close_link") or ("acx-" + command["id"][-24:])
                previous = self.api.lookup(symbol, ident)
                send = previous is None and not body.get("close_attempted")
                if previous is None and body.get("close_attempted"):
                    return  # Empty lookup after timeout does not permit a new close id.
                if previous and previous.get("orderStatus") in {"Cancelled", "Rejected", "Filled"}:
                    # IOC can leave a residual. New revision only after a terminal
                    # acknowledgement and an actual nonzero position.
                    revision = int(body.get("revision", 0)) + 1
                    body["revision"] = revision
                    ident = f"{ident[:28]}-{revision}"
                    send = True
                if send:
                    body["close_link"], body["close_attempted"] = ident, True
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE commands SET body=? WHERE id=?", (encode(body), command["id"])
                        )
                    self.api.close_position(pos, ident)
            if positions:
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE commands SET body=? WHERE id=?", (encode(body), command["id"])
                    )
                return  # Completed only on a later venue-flat observation.
        elif kind == "stop":
            _, positions, _ = self.api.account()
            for pos in positions:
                if pos["symbol"] != symbol or not float(pos.get("size") or 0):
                    continue
                current, proposed = float(pos.get("stopLoss") or 0), float(body["stop"])
                instrument = self.instruments[symbol]
                proposed = floor_step(proposed, instrument.tick)
                mark = float(pos.get("markPrice") or pos["avgPrice"])
                improves = (pos["side"] == "Buy" and current < proposed < mark) or (
                    pos["side"] == "Sell" and mark < proposed < current
                )
                if improves:
                    self.api.stop(symbol, proposed)
        else:
            raise ValueError(f"unknown command {kind}")
        with self.store.transaction() as db:
            db.execute("UPDATE commands SET state='done' WHERE id=?", (command["id"],))

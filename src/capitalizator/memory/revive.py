"""Reload pending touches from journal + stored zones. No hash append. No orders."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, get_args

from capitalizator.memory.registry import Touch
from capitalizator.ops.knowledge import Knowledge
from capitalizator.zones.model import Zone, ZoneMethod

PENDING = frozenset({None, "", "pending"})
_SIDES = frozenset({"support", "resistance"})


def _parse_utc(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return ts


def _decimal(raw: object) -> Decimal | None:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ArithmeticError, TypeError):
        return None
    return value if value > 0 else None


def zone_from_payload(row: dict[str, Any]) -> Zone | None:
    side = str(row.get("side") or "")
    method = str(row.get("method") or "")
    zid = str(row.get("zone_id") or "").strip()
    symbol = str(row.get("symbol") or "").strip()
    tf = str(row.get("tf") or "").strip()
    lo = _decimal(row.get("lo"))
    hi = _decimal(row.get("hi"))
    created = _parse_utc(row.get("created_as_of"))
    if not zid or not symbol or not tf or lo is None or hi is None or created is None:
        return None
    if side not in _SIDES or method not in get_args(ZoneMethod):
        return None
    if lo > hi:
        return None
    return Zone(
        zone_id=zid,
        symbol=symbol,
        tf=tf,
        side=side,  # type: ignore[arg-type]
        lo=lo,
        hi=hi,
        method=method,  # type: ignore[arg-type]
        created_as_of=created,
    )


def touch_from_journal(row: dict[str, Any]) -> Touch | None:
    if row.get("outcome") not in PENDING:
        return None
    touch_id = str(row.get("touch_id") or "").strip()
    zone_id = str(row.get("zone_id") or "").strip()
    ts = _parse_utc(row.get("touch_ts"))
    px = _decimal(row.get("trade_px"))
    qty = _decimal(row.get("trade_qty"))
    if not touch_id or not zone_id or ts is None or px is None or qty is None:
        return None
    return Touch(
        touch_id=touch_id,
        zone_id=zone_id,
        ts=ts,
        trade_px=px,
        trade_qty=qty,
        outcome="pending",
    )


_OUTCOMES = frozenset({"pending", "bounce", "break", "die"})


def zone_from_journal(row: dict[str, Any]) -> Zone | None:
    """The zone as the touch saw it — from the journal's own zone facts (written by the
    desk since zones retire). Rows written before those facts existed → None."""
    created = _parse_utc(row.get("zone_created_as_of")) or _parse_utc(row.get("touch_ts"))
    return zone_from_payload(
        {
            "zone_id": row.get("zone_id"),
            "symbol": row.get("symbol"),
            "tf": row.get("zone_tf"),
            "side": row.get("zone_side"),
            "lo": row.get("zone_lo"),
            "hi": row.get("zone_hi"),
            "method": row.get("zone_method"),
            "created_as_of": None if created is None else created.isoformat(),
        }
    )


def _opt_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw in (None, ""):
        return None
    return str(raw).strip().lower() in {"1", "true", "yes"}


def touch_record_from_journal(row: dict[str, Any]) -> Touch | None:
    """A journal row as a Touch with its outcome and labels — for reports that read the
    day as it happened (`touch_from_journal` rebuilds *pending* touches for revival)."""
    touch_id = str(row.get("touch_id") or "").strip()
    zone_id = str(row.get("zone_id") or "").strip()
    ts = _parse_utc(row.get("touch_ts"))
    px = _decimal(row.get("trade_px"))
    qty = _decimal(row.get("trade_qty"))
    if not touch_id or not zone_id or ts is None or px is None or qty is None:
        return None
    outcome = str(row.get("outcome") or "pending")
    if outcome not in _OUTCOMES:
        outcome = "pending"
    return Touch(
        touch_id=touch_id,
        zone_id=zone_id,
        ts=ts,
        trade_px=px,
        trade_qty=qty,
        outcome=outcome,  # type: ignore[arg-type]
        tape_eaten=_opt_bool(row.get("tape_eaten")),
        gesture=str(row["zlg_label"]) if row.get("zlg_label") else None,
        cav_label=str(row["cav_label"]) if row.get("cav_label") else None,
        jury=str(row["jury"]) if row.get("jury") else None,
        skip_reason=str(row["skip_reason"]) if row.get("skip_reason") else None,
        shadow_would=_opt_bool(row.get("shadow_would")),
        idea=str(row["idea"]) if row.get("idea") else None,
    )


def load_pending(knowledge: Knowledge) -> tuple[list[Zone], list[Touch]]:
    """Pending journal rows whose zone is still stored. Missing zone stays out."""
    if not knowledge.available():
        return [], []
    zones = {
        str(row.get("zone_id")): zone
        for row in knowledge.list_zones()
        if (zone := zone_from_payload(row)) is not None
    }
    seen: set[str] = set()
    touches: list[Touch] = []
    used_zones: dict[str, Zone] = {}
    for row in knowledge.journal_rows():
        touch = touch_from_journal(row)
        if touch is None or touch.touch_id in seen:
            continue
        zone = zones.get(touch.zone_id)
        if zone is None:
            continue
        seen.add(touch.touch_id)
        used_zones[zone.zone_id] = zone
        touches.append(touch)
    return list(used_zones.values()), touches

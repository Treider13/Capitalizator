"""Fill journal hx_* holes from closed bars. Does not invent r_net. Does not send.

Reuses build_features (PIT) and the same stamp the desk writes on a live touch.
A value already in the row stays. A future bar is dropped by build_features.
Contour A does not import this file.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.desk.bars import closed_bars_from_trades
from capitalizator.hyexec.dataset import FEATURE_KEYS, plan_from_rows
from capitalizator.hyexec.features import build_features, feature_journal
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar

HOLE = frozenset({None, "", "null", "none"})


def as_of_of(row: Mapping[str, Any]) -> datetime | None:
    raw = str(row.get("touch_ts") or row.get("hyexec_as_of") or "").strip()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(UTC)


def needs_fill(row: Mapping[str, Any]) -> bool:
    if not str(row.get("touch_id") or ""):
        return False
    return any(row.get(key) in HOLE for key in FEATURE_KEYS)


def apply_features(row: Mapping[str, Any], stamped: Mapping[str, Any]) -> dict[str, Any]:
    """Fill holes only. paper / r_net / touch_id are never taken from stamped."""
    out = dict(row)
    if out.get("hyexec_as_of") in HOLE and stamped.get("hyexec_as_of") not in HOLE:
        out["hyexec_as_of"] = stamped["hyexec_as_of"]
    for key in FEATURE_KEYS:
        if out.get(key) in HOLE and stamped.get(key) not in HOLE:
            out[key] = stamped[key]
    return out


def bars_for_symbol(
    events: Sequence[MarketEvent],
    *,
    symbol: str,
    as_of: datetime,
) -> tuple[tuple[Bar, ...], tuple[Bar, ...], tuple[Bar, ...]]:
    m1 = tuple(closed_bars_from_trades(events, symbol=symbol, tf="1m", now=as_of, already=set()))
    m5 = tuple(closed_bars_from_trades(events, symbol=symbol, tf="5m", now=as_of, already=set()))
    h1 = tuple(closed_bars_from_trades(events, symbol=symbol, tf="1h", now=as_of, already=set()))
    return m1, m5, h1


BarsFn = Callable[[str, datetime], tuple[Sequence[Bar], Sequence[Bar], Sequence[Bar]]]


def backfill_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bars: BarsFn | None = None,
    events: Sequence[MarketEvent] = (),
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, n_changed). Missing bars leave the hole. No fill-with-zero."""
    out: list[dict[str, Any]] = []
    changed = 0
    for row in rows:
        body = dict(row)
        if not needs_fill(body):
            out.append(body)
            continue
        when = as_of_of(body)
        symbol = str(body.get("symbol") or "")
        if when is None or not symbol:
            out.append(body)
            continue
        if bars is not None:
            m1, m5, h1 = bars(symbol, when)
        else:
            m1, m5, h1 = bars_for_symbol(events, symbol=symbol, as_of=when)
        stamped = feature_journal(
            build_features(bars_1m=m1, bars_5m=m5, bars_1h=h1, as_of=when)
        )
        filled = apply_features(body, stamped)
        if filled != body:
            changed += 1
        out.append(filled)
    return out, changed


def backfill_knowledge(knowledge: Any, *, events: Sequence[MarketEvent] = ()) -> dict[str, Any]:
    rows = knowledge.journal_rows() if knowledge.available() else []
    filled, n_changed = backfill_rows(rows, events=events)
    if n_changed and knowledge.available():
        for row in filled:
            tid = str(row.get("touch_id") or "")
            if tid:
                knowledge.put_journal_touch(tid, row)
    plan = plan_from_rows(knowledge.journal_rows() if knowledge.available() else filled)
    plan["filled"] = n_changed
    return plan


def backfill_vault(vault: Any, *, tape: Path | None = None) -> dict[str, Any]:
    from capitalizator.hyexec.tape_day import load_trade_events
    from capitalizator.ops.knowledge import open_knowledge

    knowledge = open_knowledge(vault)
    try:
        events: list[MarketEvent] = []
        root = tape if tape is not None else vault.tape
        rows = knowledge.journal_rows() if knowledge.available() else []
        symbols = {str(r.get("symbol") or "") for r in rows if needs_fill(r)}
        symbols.discard("")
        if symbols and root.is_dir():
            events = load_trade_events(root, symbols=symbols)
        return backfill_knowledge(knowledge, events=events)
    finally:
        knowledge.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill journal hx_* holes. Does not send.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--tape", default="")
    args = parser.parse_args(argv)
    from capitalizator.ops.vault import load_vault

    tape = Path(args.tape) if args.tape else None
    plan = backfill_vault(load_vault(Path(args.userdir)), tape=tape)
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded, read-only operator journals. No arbitrary SQL or secrets metadata."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from capitalizator.fusion.store import Store

TABLES = frozenset(
    {
        "contracts",
        "decisions",
        "orders",
        "executions",
        "commands",
        "models",
        "events",
        "archives",
        "headlines",
        "samples",
        "dispatch",
    }
)
ACCOUNT_TABLES = frozenset({"orders", "executions", "commands", "dispatch"})


def records(
    store: Store, mode: str, kind: str, limit: int = 20, before: int | None = None
) -> dict[str, Any]:
    if kind not in TABLES:
        raise ValueError("unsupported journal")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if before is not None and (type(before) is not int or not 0 < before < 2**63):
        raise ValueError("invalid journal cursor")
    if mode not in {"demo", "live"}:
        raise ValueError("invalid account mode")
    table = "meta" if kind in {"archives", "headlines"} else kind
    filters: list[str] = []
    args: list[Any] = []
    if kind == "archives":
        filters.append("key LIKE 'archive:%'")
    if kind == "headlines":
        filters.append("key LIKE 'news_item:%'")
    if kind == "dispatch":
        filters.append(
            "((kind='command' AND EXISTS (SELECT 1 FROM commands c "
            "WHERE c.id=dispatch.id AND c.mode=?)) OR "
            "(kind IN ('order','cancel') AND EXISTS (SELECT 1 FROM orders o "
            "WHERE o.id=dispatch.id AND o.mode=?)))"
        )
        args.extend((mode, mode))
    elif kind in ACCOUNT_TABLES:
        filters.append("mode=?")
        args.append(mode)
    if before is not None:
        filters.append("rowid<?")
        args.append(before)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    # The table identifier comes exclusively from TABLES; all values are parameters.
    rows = read_journal(
        store,
        f"SELECT rowid AS cursor,* FROM {table}{where} ORDER BY rowid DESC LIMIT ?",
        (*args, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "kind": kind,
        "mode": mode if kind in ACCOUNT_TABLES else None,
        "rows": rows,
        "next_before": rows[-1]["cursor"] if more else None,
    }


def read_journal(store: Store, sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Independent WAL reader: long operator reads never own the trading lock."""
    deadline = time.monotonic() + 0.5
    db = sqlite3.connect(store.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return [dict(row) for row in db.execute(sql, args).fetchall()]
    finally:
        db.close()

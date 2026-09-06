"""Bounded, read-only operator journals. No arbitrary SQL or secrets metadata."""

from __future__ import annotations

from typing import Any

from capitalizator.fusion.store import Store

TABLES = frozenset(
    {"contracts", "decisions", "orders", "executions", "commands", "models", "events", "archives"}
)
ACCOUNT_TABLES = frozenset({"orders", "executions", "commands"})


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
    table = "meta" if kind == "archives" else kind
    filters: list[str] = []
    args: list[Any] = []
    if kind == "archives":
        filters.append("key LIKE 'archive:%'")
    if kind in ACCOUNT_TABLES:
        filters.append("mode=?")
        args.append(mode)
    if before is not None:
        filters.append("rowid<?")
        args.append(before)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    # The table identifier comes exclusively from TABLES; all values are parameters.
    rows = store.rows(
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

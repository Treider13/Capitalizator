"""Container health probe: is the process heartbeat in SQLite fresh?

`python -m capitalizator.ops.healthz --userdir /data --heartbeat desk_heartbeat --max-age-s 120`
exits 0 when `meta[heartbeat]` is an ISO timestamp younger than `max_age_s`, 1 otherwise.
An import check ("python -c 'import capitalizator'") says nothing about a hung loop.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import load_vault


def heartbeat_age_s(userdir: Path, key: str, *, now: datetime | None = None) -> float | None:
    """Seconds since the heartbeat, None when absent/unreadable."""
    try:
        knowledge = open_knowledge(load_vault(userdir))
    except Exception:
        return None
    try:
        raw = knowledge.meta(key) if knowledge.available() else None
    finally:
        knowledge.close()
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return ((now or datetime.now(tz=UTC)) - at).total_seconds()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Heartbeat freshness probe.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--heartbeat", required=True)
    parser.add_argument("--max-age-s", type=float, default=120.0)
    args = parser.parse_args(argv)
    age = heartbeat_age_s(Path(args.userdir), args.heartbeat)
    if age is None or age > args.max_age_s:
        state = "absent" if age is None else f"{age:.0f}s old"
        print(f"{args.heartbeat}: {state}", file=sys.stderr)
        return 1
    print(f"{args.heartbeat}: {age:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

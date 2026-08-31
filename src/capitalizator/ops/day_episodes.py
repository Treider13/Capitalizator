"""Evening list of paper episodes. No file → 0 rows, not a made-up trade."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD or 'today'")
    parser.add_argument("--file", default="")
    args = parser.parse_args(argv)
    if args.date == "today":
        day = datetime.now(UTC).date()
    else:
        day = date.fromisoformat(args.date)
    path = Path(args.file) if args.file else None
    if path is None or not path.is_file():
        print(json.dumps({"date": day.isoformat(), "n": 0, "episodes": []}))
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("episodes") or []
    print(json.dumps({"date": day.isoformat(), "n": len(rows), "episodes": rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

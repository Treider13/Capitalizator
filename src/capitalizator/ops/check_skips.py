"""Skip journal for a window. No file → n=0, exit 2. Does not invent reasons."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--file", default="")
    args = parser.parse_args(argv)
    if args.days <= 0:
        print(json.dumps({"n": 0, "ok": False, "reason": "days must be > 0"}))
        return 2
    path = Path(args.file) if args.file else None
    if path is None or not path.is_file():
        print(json.dumps({"n": 0, "ok": False, "reason": "missing file"}))
        return 2
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("skips") or []
    print(json.dumps({"n": len(rows), "ok": len(rows) > 0, "days": args.days}))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())

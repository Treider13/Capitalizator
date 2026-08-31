"""Count raw author_call rows. Exit 2 if below --min. Does not invent posts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from capitalizator.authors.ingest import AuthorsIngest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--min", dest="minimum", type=int, default=20)
    args = parser.parse_args(argv)
    path = Path(args.file)
    if not path.is_file():
        print(json.dumps({"n": 0, "ok": False, "reason": "missing file"}))
        return 2
    batch = AuthorsIngest.from_jsonl(path)
    n = len(batch.rows)
    ok = n >= args.minimum
    print(json.dumps({"n": n, "min": args.minimum, "ok": ok}))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

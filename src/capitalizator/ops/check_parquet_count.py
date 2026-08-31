"""Compare parquet row count to an expected integer. Exact, not approximate."""

from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow.parquet as pq


def count_rows(path: Path) -> int:
    meta = pq.ParquetFile(path).metadata
    if meta is None:
        raise ValueError(f"parquet metadata missing: {path}")
    return int(meta.num_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--expect", type=int, required=True)
    args = parser.parse_args(argv)
    got = count_rows(Path(args.path))
    if got != args.expect:
        raise SystemExit(f"row count {got} != expect {args.expect}")
    print(got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Compact the tape archive: merge an hour's parquet parts into one file, drop old live feeds.

The recorder writes `hour=HH.<seq>.parquet` parts once a minute and appends the live
`hour=HH.jsonl` per event (desk/tape.py tails it). Left alone that is ~1 500 parts a
day per symbol × stream. This job, run hourly by the `night` service:

  * for every partition older than `min_age_h` hours: read all `hour=HH*.parquet`,
    sort by (exchange_ts, seq), write one `hour=HH.parquet` atomically, delete the
    parts. Row count is verified before anything is deleted;
  * deletes `hour=HH.jsonl` live feeds older than `jsonl_keep_h` hours (the parquet
    holds the same rows; the desk only tails recent hours).

Never touches the current hour or the previous one. Idempotent. No keys.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from capitalizator.ops.vault import iter_regular_files
from capitalizator.recorder.sink_parquet import SCHEMA

_PART = re.compile(r"^hour=(\d{2})(?:\.(\d{6}))?\.parquet$")
_LIVE = re.compile(r"^hour=(\d{2})\.jsonl$")


def _hour_of(path: Path, hh: str) -> datetime | None:
    for part in path.parts:
        if part.startswith("date="):
            try:
                day = datetime.strptime(part[5:], "%Y-%m-%d")
            except ValueError:
                return None
            return day.replace(hour=int(hh), tzinfo=UTC)
    return None


def compact(
    tape: Path,
    *,
    now: datetime | None = None,
    min_age_h: int = 2,
    jsonl_keep_h: int = 48,
) -> dict[str, int]:
    when = now or datetime.now(tz=UTC)
    groups: dict[Path, list[Path]] = {}
    live: list[tuple[Path, datetime]] = []
    for path in iter_regular_files(tape):
        m = _PART.match(path.name)
        if m:
            start = _hour_of(path, m.group(1))
            if start is None or when - start < timedelta(hours=min_age_h + 1):
                continue
            groups.setdefault(path.parent / f"hour={m.group(1)}.parquet", []).append(path)
            continue
        ml = _LIVE.match(path.name)
        if ml:
            start = _hour_of(path, ml.group(1))
            if start is not None:
                live.append((path, start))
    merged = parts_removed = rows = 0
    for target, parts in sorted(groups.items()):
        if len(parts) == 1 and parts[0] == target:
            continue  # already a single file
        tables = []
        for part in sorted(parts):
            try:
                tables.append(pq.read_table(part, schema=SCHEMA))
            except (OSError, pa.ArrowInvalid):
                tables = []
                break
        if not tables:
            continue
        table = pa.concat_tables(tables)
        if table.num_rows == 0:
            continue
        order = pa.compute.sort_indices(
            table, sort_keys=[("exchange_ts", "ascending"), ("seq", "ascending")]
        )
        table = table.take(order)
        expected = sum(t.num_rows for t in tables)
        tmp = target.with_name(target.name + ".compact.tmp")
        pq.write_table(table, tmp)
        if pq.ParquetFile(tmp).metadata.num_rows != expected:
            tmp.unlink(missing_ok=True)
            continue
        os.replace(tmp, target)
        for part in parts:
            if part != target:
                part.unlink(missing_ok=True)
                parts_removed += 1
        merged += 1
        rows += expected
    live_removed = 0
    for path, start in live:
        if when - start > timedelta(hours=jsonl_keep_h):
            path.unlink(missing_ok=True)
            live_removed += 1
    return {
        "hours_merged": merged,
        "parts_removed": parts_removed,
        "rows": rows,
        "live_removed": live_removed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compact tape parquet parts. No keys.")
    parser.add_argument("--tape", required=True)
    parser.add_argument("--min-age-h", type=int, default=2)
    parser.add_argument("--jsonl-keep-h", type=int, default=48)
    args = parser.parse_args(argv)
    out = compact(Path(args.tape), min_age_h=args.min_age_h, jsonl_keep_h=args.jsonl_keep_h)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

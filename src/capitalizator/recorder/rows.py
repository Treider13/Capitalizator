"""Column-wise Parquet → row dicts without per-value `import pytz` retries.

`pyarrow.Table.to_pylist()` converts tz-aware timestamps by trying `import pytz`
for every value; pytz is deliberately not installed here, so a 1h tape caused
~100k failing import lookups (profile, D-28). Timestamps are read as int64 and
rebuilt exactly with timedelta.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SCALE = {"s": 1_000_000, "ms": 1_000, "us": 1}


def rows_fast(table: pa.Table) -> list[dict[str, Any]]:
    n = table.num_rows
    if n == 0:
        return []
    cols: dict[str, list[Any]] = {}
    for name in table.column_names:
        col = table.column(name)
        if pa.types.is_timestamp(col.type):
            unit = col.type.unit
            raw = col.cast(pa.int64()).to_pylist()
            out: list[Any] = []
            for v in raw:
                if v is None:
                    out.append(None)
                elif unit == "ns":
                    out.append(_EPOCH + timedelta(microseconds=v // 1000))
                else:
                    out.append(_EPOCH + timedelta(microseconds=v * _SCALE[unit]))
            cols[name] = out
        else:
            cols[name] = col.to_pylist()
    keys = list(cols)
    return [{k: cols[k][i] for k in keys} for i in range(n)]

"""2.11.2 — «N из M» is the two integers a PIT SQL must return on as_of.

Same SQL + a swapped number is REFUTED. No store / not two integers →
UNVERIFIABLE. Does not let an LLM set VERIFIED. Does not invent rows.
"""

from __future__ import annotations

import re
from datetime import datetime

from capitalizator.storage.pit import PitStore
from capitalizator.types import require_utc
from capitalizator.verifier.manual import BindReceipt, Verdict

_CLAIM = re.compile(r"^(\d+)\s+из\s+(\d+)$")


class SqlVerifier:
    def recompute(
        self,
        claim: str,
        sql: str,
        store: PitStore | None,
        *,
        as_of: datetime,
    ) -> BindReceipt:
        text = claim.strip()
        parsed = _CLAIM.fullmatch(text)
        if parsed is None or store is None or not sql.strip():
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        require_utc(as_of)
        try:
            rows = store.query(sql, as_of=as_of)
        except Exception:
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        if len(rows) != 1:
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        values = list(rows[0].values())
        if len(values) != 2:
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        try:
            got = (int(values[0]), int(values[1]))
        except (TypeError, ValueError):
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        want = (int(parsed.group(1)), int(parsed.group(2)))
        verdict: Verdict = "VERIFIED" if got == want else "REFUTED"
        return BindReceipt(claim=text, verdict=verdict, sql_path=None)

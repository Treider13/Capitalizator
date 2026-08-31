"""1.7.2 — VERIFIED only if a recorded query result matches the claim.

A number with no query file cannot be VERIFIED. This does not run DuckDB
on invented rows and does not call an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Verdict = Literal["VERIFIED", "REFUTED", "UNVERIFIABLE"]


@dataclass(frozen=True)
class BindReceipt:
    claim: str
    verdict: Verdict
    sql_path: str | None


class ManualVerifier:
    def bind(self, claim: str, sql_path: Path | str | None, result: str | None) -> BindReceipt:
        text = claim.strip()
        if not text:
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        if sql_path is None:
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=None)
        path = Path(sql_path)
        if not path.is_file():
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=str(path))
        recorded = path.read_text(encoding="utf-8").strip()
        if result is None:
            return BindReceipt(claim=text, verdict="UNVERIFIABLE", sql_path=str(path))
        verdict: Verdict = (
            "VERIFIED" if recorded == result == text else "REFUTED"
        )
        return BindReceipt(claim=text, verdict=verdict, sql_path=str(path))

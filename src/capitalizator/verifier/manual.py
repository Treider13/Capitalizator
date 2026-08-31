"""1.7.2 — VERIFIED only if a recorded query result matches the claim.

A number with no query file cannot be VERIFIED. This does not run DuckDB
on invented rows and does not call an LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

Verdict = Literal["VERIFIED", "REFUTED", "UNVERIFIABLE"]


class ManualVerifier:
    def bind(self, claim: str, sql_path: Path | str | None, result: str | None) -> Verdict:
        if not claim.strip():
            return "UNVERIFIABLE"
        if sql_path is None:
            return "UNVERIFIABLE"
        path = Path(sql_path)
        if not path.is_file():
            return "UNVERIFIABLE"
        recorded = path.read_text(encoding="utf-8").strip()
        if result is None:
            return "UNVERIFIABLE"
        if recorded == result == claim.strip():
            return "VERIFIED"
        return "REFUTED"

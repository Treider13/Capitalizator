"""'23 of 31' without a query file cannot be VERIFIED."""

from __future__ import annotations

from pathlib import Path

from capitalizator.verifier.manual import BindReceipt, ManualVerifier


def test_claim_without_query_is_not_verified() -> None:
    got = ManualVerifier().bind("23 из 31", None, "23 из 31")
    assert got == BindReceipt(claim="23 из 31", verdict="UNVERIFIABLE", sql_path=None)


def test_matching_query_file_is_verified(tmp_path: Path) -> None:
    q = tmp_path / "count.txt"
    q.write_text("23 из 31\n", encoding="utf-8")
    got = ManualVerifier().bind("23 из 31", q, "23 из 31")
    assert got.verdict == "VERIFIED"
    assert got.claim == "23 из 31"
    assert got.sql_path == str(q)


def test_mismatch_is_refuted(tmp_path: Path) -> None:
    q = tmp_path / "count.txt"
    q.write_text("10 из 31\n", encoding="utf-8")
    got = ManualVerifier().bind("23 из 31", q, "23 из 31")
    assert got.verdict == "REFUTED"
    assert got.sql_path == str(q)

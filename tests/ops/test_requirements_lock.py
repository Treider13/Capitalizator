"""Lock file must list runtime deps. A stale lock is a lie."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()


def test_lock_covers_runtime_packages() -> None:
    for name in ("pydantic", "pyarrow", "duckdb", "pyyaml"):
        assert name in LOCK, f"{name} missing from requirements.lock"


def test_lock_does_not_claim_unused_pytz() -> None:
    assert "pytz" not in LOCK

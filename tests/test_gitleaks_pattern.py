"""−1.2: fixture looks like a secret; src must not."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "gitleaks" / "fake_secret.txt"
SRC = ROOT / "src"


def test_fixture_contains_key_pattern() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert "BYBIT_API_KEY=" in text
    assert "ghp_" in text


def test_src_has_no_key_literals() -> None:
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        blob = path.read_text(encoding="utf-8", errors="ignore")
        assert "BYBIT_API_KEY=" not in blob
        assert "AKIA" not in blob


def test_gitleaks_fails_on_fixture_if_installed() -> None:
    exe = shutil.which("gitleaks")
    if exe is None:
        pytest.skip("gitleaks binary not installed")
    proc = subprocess.run(
        [exe, "detect", "--no-git", "--no-banner", "-s", str(FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr

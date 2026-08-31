"""0.1.2 template is in git. Values of keys are not."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "ops" / "key-checklist.md"


def test_checklist_is_a_template_without_secrets() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    assert "Withdraw" in text
    assert "Сабаккаунт" in text
    assert "не зелёный" in text
    assert "ghp_" not in text
    assert "BYBIT_API_KEY=" not in text
    assert "sk-" not in text

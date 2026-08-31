"""2.11.5 — LLM package cannot assign VERIFIED. Scan, do not invent a model."""

from __future__ import annotations

from pathlib import Path

LLM = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "llm"


def test_llm_sources_do_not_assign_verified() -> None:
    banned = ("verdict = \"VERIFIED\"", "verdict='VERIFIED'", ".verdict = \"VERIFIED\"")
    hits: list[str] = []
    for path in sorted(LLM.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                hits.append(f"{path.name}:{token}")
    assert hits == []

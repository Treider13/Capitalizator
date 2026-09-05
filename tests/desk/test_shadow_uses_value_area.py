"""Shadow stop must share live VAH/VAL geometry. Same initial_stop, same card."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "desk" / "loop.py"


def test_submit_paper_passes_value_area_into_smart_stop() -> None:
    text = SRC.read_text(encoding="utf-8")
    start = text.index("def _submit_paper(")
    end = text.index("decision = size_position(", start)
    block = text[start:end]
    assert "vah=self._value_area(st.zlg_card)[0]" in block
    assert "val=self._value_area(st.zlg_card)[1]" in block

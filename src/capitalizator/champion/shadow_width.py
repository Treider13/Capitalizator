"""1.7.5 — replay the same day at zone_width ×0.8 and ×1.2. No orders.

Champion is not swapped. Night report only.
"""

from __future__ import annotations

from decimal import Decimal

WIDTHS = (Decimal("0.8"), Decimal("1.2"))


class ShadowWidth:
    def __init__(self, *, champion_width: Decimal = Decimal("1")) -> None:
        if champion_width <= 0:
            raise ValueError("champion_width must be > 0")
        self.champion_width = champion_width

    def report(self) -> list[dict[str, object]]:
        return [
            {"width": width, "orders": False, "role": "challenger"} for width in WIDTHS
        ]

    def promote(self, paper_rows=None, *, now=None, ack: bool = False):  # type: ignore[no-untyped-def]
        """No auto promote. With `ack` and paper rows, runs the exam and returns the
        report; the desk flips the champion label only on a pass (champion/exam.py)."""
        if not ack or paper_rows is None or now is None:
            raise ValueError("no auto promote; the exam needs paper rows, a clock and an ack")
        from capitalizator.champion.exam import exam

        return exam(paper_rows, now=now)

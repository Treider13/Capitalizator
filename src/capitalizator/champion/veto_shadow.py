"""2.9.5 — night report: same day with veto on vs off. No orders.

Champion stays the law. Challenger is not switched on tomorrow.
"""

from __future__ import annotations


class VetoShadow:
    def report(self) -> list[dict[str, object]]:
        return [
            {"veto": True, "orders": False, "role": "champion"},
            {"veto": False, "orders": False, "role": "challenger"},
        ]

    def promote(self, paper_rows=None, *, now=None, ack: bool = False):  # type: ignore[no-untyped-def]
        """No auto promote. With `ack` and paper rows, runs the exam (champion/exam.py)."""
        if not ack or paper_rows is None or now is None:
            raise ValueError("no auto promote; the exam needs paper rows, a clock and an ack")
        from capitalizator.champion.exam import exam

        return exam(paper_rows, now=now)

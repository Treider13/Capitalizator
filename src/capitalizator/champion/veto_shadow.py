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

    def promote(self) -> None:
        raise ValueError("no auto promote; exam is 15-20 days")

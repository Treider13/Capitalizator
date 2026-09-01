"""5.23 paper — F5 1.2% only after G4 and equity_source=main.

Does not write phase.yaml. Does not raise lev. F1 stays 1%.
"""

from __future__ import annotations

from decimal import Decimal

F1_TARGET = Decimal("0.01")
F5_TARGET = Decimal("0.012")


def f5_target(*, equity_source: str, gate_f4: bool, ack: bool = False) -> Decimal | None:
    """1.2% only after G4 + equity_source=main + human ack. Else 1%."""
    if equity_source != "main" or not gate_f4 or not ack:
        return None
    return F5_TARGET


def active_target(*, equity_source: str, gate_f4: bool, ack: bool = False) -> Decimal:
    got = f5_target(equity_source=equity_source, gate_f4=gate_f4, ack=ack)
    if got is None:
        return F1_TARGET
    return got

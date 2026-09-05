"""3.14.3 — a REFUTED load-bearing claim (or a B veto) flattens. Not 'wait and see'.

The +1R half and the trail live where the fills are: `exec/paper.py` (paper
twins) and `exec/trail.py` (structure / venue trailing). The old `on_fill` /
`trail_stop` shims here were never called by the desk and are gone (audit §1).
Does not place an order. Does not add size. No mechanical break-even knob.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from capitalizator.hyexec.pyramid import ProfitAdd
from capitalizator.risk.schema import ManageIntent


class TradeManager:
    def on_refute(self, *, load_bearing: bool, verdict: str) -> ManageIntent | None:
        if load_bearing and verdict in {"REFUTED", "veto"}:
            return ManageIntent(action="flatten")
        return None

    def add_in_profit(
        self,
        *,
        side: Literal["buy", "sell"],
        entry: Decimal,
        add_price: Decimal,
        extra_risk: Decimal,
        open_risk: Decimal,
    ) -> ProfitAdd:
        return ProfitAdd(
            side=side,
            entry=entry,
            add_price=add_price,
            extra_risk=extra_risk,
            open_risk=open_risk,
        )

"""Daily report → JSON. No trades. No network. No LLM API.

This is a deterministic recap of the evening map. A model may later sit
behind the same schema; it cannot set trade_advice true or emit advice tokens.
"""

from __future__ import annotations

import re
from typing import Any

from capitalizator.llm.sandbox import no_egress

_ADVICE = re.compile(
    r"лонг|шорт|купи|продай|завтра|долей|усредн|average_in|martingale|pyramid",
    re.IGNORECASE,
)
_POISON = re.compile(
    r"VERIFIED|REFUTED|UNVERIFIABLE|API_?KEY|API_?SECRET|os\.environ",
    re.IGNORECASE,
)


class DailySummary:
    prompt = (
        "Перескажи вечерний отчёт. Не предлагай сделок. "
        "Не пиши лонг, шорт, купи, продай, завтра, долей."
    )

    def run(self, report: str) -> dict[str, Any]:
        with no_egress():
            lines = [ln.strip() for ln in report.splitlines() if ln.strip()]
            body = " ".join(lines[:3]) if lines else "Отчёт пуст."
            if _ADVICE.search(body) or _POISON.search(body):
                body = "Отчёт содержит запрещённые слова; пересказ без советов."
            out = {"summary": body, "trade_advice": False}
            if out["trade_advice"] is not False:
                raise ValueError("trade_advice must stay false")
            if _ADVICE.search(out["summary"]) or _POISON.search(out["summary"]):
                raise ValueError("summary must not advise")
            return out

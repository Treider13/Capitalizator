# exec

Вход: `ReplayEngine.run(path)` — jsonl книги; `tape(path)` — `trades.jsonl` если есть.
Выход: контрольные `best()`; лента как MarketEvent. Нет файла сделок — пустой список, не выдумка.
`FeeTable.VIP0`: 0.0002 / 0.00055 ×2 номинала (PHASE-BUILD). `NaiveQueueFill`: печать пересекла лимит, не close свечи.

Не делает: live-ордер, стратегию, выдуманный стакан на дыре.
Ключи не читает.

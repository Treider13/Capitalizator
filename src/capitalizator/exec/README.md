# exec

Вход: `ReplayEngine.run(path)` — jsonl книги; `tape(path)` — `trades.jsonl` если есть.
Выход: контрольные `best()`; лента как MarketEvent. Нет файла сделок — пустой список, не выдумка.
`FeeTable.VIP0`: 0.0002 / 0.00055 ×2 номинала (PHASE-BUILD). `NaiveQueueFill`: печать пересекла лимит, не close свечи.

`DemoAdapter`: только `trading_mode=demo`. Сейчас phase=off → отказ. Host mainnet в файле нет. Hello на биржу не шлём.

Не делает: live-ордер, стратегию, выдуманный стакан на дыре.
Ключи не читает.

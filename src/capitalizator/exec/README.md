# exec

Вход: `ReplayEngine.run(path)`; `BounceStrategy.propose(snapshot)` — все 5 гейтов.
Выход: контрольные `best()`; `Intent` с `tag=bounce` или None. `TradeManager`: 50% на +1R, нет БУ на +2%.
`DemoAdapter`: только `trading_mode=demo`. Сейчас phase=off → отказ. Hello на биржу не шлём.
`TAKER_OK=false`. Карточка по умолчанию обязательна. `TcaTable` пустая → медиана None. `EpisodeLog` пустой, пока нет демо-входа.

Не делает: live-ордер, submit из стратегии, механический BE, выдуманный стакан.
Ключи не читает.

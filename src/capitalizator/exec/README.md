# exec

Вход: `ReplayEngine.run(path)`; `BounceStrategy.propose(snapshot)` — все 5 гейтов.
Выход: контрольные `best()`; `Intent` с `tag=bounce` или None. `TradeManager`: 50% на +1R, нет БУ на +2%.
`DemoAdapter`: только `trading_mode=demo`. Сейчас phase=off → отказ. Hello на биржу не шлём.
`TAKER_OK=false`. Карточка по умолчанию обязательна. `TcaTable` пустая → медиана None. `EpisodeLog` пустой, пока нет демо-входа.

`FirstMinute.blocks` — бумага для пробоя: `exchange_ts < close + 60s`. `propose` отскока это не читает. `BreakoutStrategy` нет.
`FailedBreak.tag` — фитиль за зоной, close внутри → `failed_break`. Это не вход и не пробой.
`TradeManager.on_refute` — несущий REFUTED → flatten. `ShadowWriter` пишет `sent=false`, signer не импортирует.

Не делает: live-ордер, submit из стратегии, механический BE, выдуманный стакан, вход на первой минуте выноса.
Ключи не читает.

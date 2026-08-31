# recorder

Вход: публичные WS/REST потоки (trades, book, funding, OI).
Выход: MarketEvent с exchange_ts и recv_ts.
Не делает: ордера, хранение ключей, торговлю.
Ключи не читает.

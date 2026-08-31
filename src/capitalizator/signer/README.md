# signer

Вход: unsigned intent (symbol из week0, stop, `trading_mode=testnet`).
Выход: `Order` той же формы. Бирже не шлём.
`DeadMan`: тишина >30 с → `cancel_all` (колбэк, не биржа). `Reconciler.tick`: список ордеров биржи = истина.
Позиция на бирже без локальной идеи → `unknown_position` = flatten+halt+CRITICAL. Ордер flatten не шлём.

Не делает: mainnet, withdraw, чтение ключа, hello на тестнете (ключа нет).
Ключи не читает.

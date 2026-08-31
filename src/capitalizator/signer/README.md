# signer

Вход: unsigned intent (symbol из week0, stop, `trading_mode=testnet`).
Выход: `Order` той же формы. Бирже не шлём.
Не делает: mainnet, withdraw, чтение ключа, hello на тестнете (ключа нет).
Ключи не читает.

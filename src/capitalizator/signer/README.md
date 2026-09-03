# signer

Вход: unsigned intent (символ вселенной стола, stop, `trading_mode=testnet|mainnet`).
Выход: `Order` той же формы, затем send.

- `user_mode=demo` — бумага, send = `not_sent`.
- `user_mode=live` + `--cred-file` — POST linear limit на Bybit mainnet (стоп обязателен, PostOnly). Withdraw нет.
- Нет файла — live падает честно, ордер не рисуется как sent.

`DeadMan`: тишина >30 с → `cancel-all` linear (если live и cred есть).
Ключ читает только этот процесс. Desk и консоль файл не открывают.

```
python -m capitalizator.signer --userdir /var/lib/capitalizator --cred-file /etc/capitalizator/bybit.cred --serve
```

Файл `0600`, поля `id=` и `seed=`. Симлинк / world-readable — отказ.

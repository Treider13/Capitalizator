# recorder

Вход: уже разобранные кадры WS/REST (trades, book). Живой сокет — шаг VPS, не этот процесс.
Выход: MarketEvent с exchange_ts и recv_ts; parquet через `--from-jsonl`.
Не делает: ордера, ключи, выдуманный час live WS.
Ключи не читает.

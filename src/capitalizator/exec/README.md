# exec

Вход: `ReplayEngine.run(path)` — jsonl книги (фикстура `tests/fixtures/day_btc_small/`).
Выход: список `BookCheckpoint` с `best()` после каждого кадра.
Не делает: live-ордер, fill, стратегию, выдуманный стакан на дыре.
Ключи не читает.

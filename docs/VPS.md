# Чеклист установки на VPS

Канон: [`PRODUCT.md`](PRODUCT.md). Бот не пишет `infra/phase.yaml`. Ордеров 24/7 нет.

## До первой минуты записи

1. Каталог пользователя: `python -m capitalizator.ops.console --userdir ./user_data --init`
2. Ключ live — `user_data/live.cred` с формы Chronos, не в репозитории и не в `secrets/`. Симлинк / FIFO / hardlink — отказ.
3. Вселенная: `infra/universe.yaml` = 24 линейных USDT-перпа. `universe.week0.yaml` не трогать.
4. `user_mode=off` в SQLite. Демо/реал — кнопки Chronos (`POST /api/mode` + ack с localhost).
5. Hello — кнопка «Отметить hello» или первая кнопка demo/live в Хроносе (`POST /api/hello` + ack). Это флаг SQLite, не биржа. Без флага `demo`/`live` дают 403. `--mark-hello` у signer остаётся запасным.
6. Рекордер: `--minutes` + `--data-root` (без JSONL — живая лента). Сокет инжектируется на VPS.
7. Подписка: trades + book + funding + OI на 24 символа. Gap → resync, глубину не выдумывать.
8. Консоль: `python -m capitalizator.ops.console --userdir ./user_data --serve` → интерфейс «Хронос» на `http://127.0.0.1:8082/`. Туннель `ssh -L 8082:127.0.0.1:8082`. Блок «Контур» показывает on/off и сутки ленты; кнопка «Включить контур» активна только при `can_enable`. Журнал касаний пишется всегда, контур это не выключает. `POST /order` = 405. Без ленты блоки честно пустые.
9. Signer — отдельный процесс. Desk пишет `intent_queue`. Ключ — файл, не стол.
10. Dead-man 30 с, reconcile 60 с. Ночной replay + daily report + overlay. Карточка-черновик: 5–7 pending, вердикт не от LLM.
11. Desk: `python -m capitalizator.desk --userdir ./user_data --serve` читает `tape/` (parquet рекордера), пишет journal + тень + `intent_queue`. `--once` — один проход без сети. SIGINT/SIGTERM останавливают `--serve`.
12. Ключ live: форма «Сохранить ключ для live» в Хроносе пишет `user_data/live.cred` (`id=` / `seed=`, `0600`). Signer: `python -m capitalizator.signer --userdir ./user_data --serve` читает этот файл на каждую отправку. `--cred-file` остаётся, если файл лежит иначе. Withdraw в процессе нет — галочка в `ops/key-checklist.md` до ключа. Без файла `live` не шлёт.

## Не ставить в первый релиз

Nautilus, ClickHouse, shadow opponent, публичный дашборд, крипто-LOBSTER, фандинг-керри, Deribit GEX без фида, авто-promote, риск 2%, торговля вне окна 16:30–19:30 МСК, скрейп TV/TG, копия кита, ICT-движок, грид, DCA, HTX.

## Проверка после установки

```
python3.12 -m pytest tests/product/test_acceptance.py tests/ops/test_product.py -q
python -m capitalizator.ops.console --userdir ./user_data
```

Пустой журнал — честно. Суток ленты нет, пока рекордер не снял 24 часа без дыры.

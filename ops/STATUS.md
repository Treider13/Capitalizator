# Статус шагов (честно)

Дата проверки: 2026-08-31. Локально: **138 passed, 1 skipped** (skip = нет egress на `api.bybit.com`). GitHub Actions на ветке — **startup_failure** (пустой список workflows в API; админа у агента нет). Это не «CI зелёный».

| Шаг | Код / тест | Живое железо | Итог |
|---|---|---|---|
| −1.1 каркас | pytest `tests/test_import.py` | не нужно | зелёный после прогона |
| −1.2 замки | ruff + gitleaks-конфиг + `.github/workflows/lint.yml` | хук и Actions включает человек | конфиг и workflow-файл есть. gitleaks без бинаря = skip, не тихий pass. GH Actions **startup_failure** — не зелёный |
| −1.3 нет доливки | `tests/risk/test_no_average.py` | не нужно | зелёный после прогона |
| −1.4 PIT | `tests/test_pit.py` | не нужно | зелёный после прогона |
| 0.1.1 VPS SG/TYO | — | нет | **не зелёный** |
| 0.1.2 ключи | `ops/key-checklist.md` шаблон без значений | галочки человек не ставил | шаблон есть; **не зелёный** |
| 0.1.3 docker healthz | `tests/recorder/test_app.py`, `tests/infra/test_recorder_docker.py` | docker на VPS нет | Dockerfile/compose без ключей; compose up на VPS — **нет** |
| 0.1.4 WS час BTC | `BybitTradesWs.run()` + `--from-jsonl`; topic `publicTrade.BTCUSDT`, URL `wss://stream.bybit.com/v5/public/linear` | живой час нет | ack `op=subscribe` не пишется как сделка. `--minutes` без jsonl — отказ. Час записи — **нет** |
| 0.1.5 parquet | `tests/recorder/test_parquet_sink.py` | не нужно | зелёный после прогона |
| 0.1.6 gap | `tests/recorder/test_gap.py` | не нужно | зелёный после прогона |
| 0.1.7 сутки | `check_uptime` на фикстурах | нет живых суток | инструмент есть; сутки — **не зелёные** |
| 0.2.1 REST snapshot | `tests/recorder/test_snapshot.py` | curl с VPS нет | `exchange_ts` = `cts` (движок, стыкуется с `T` сделки), не системный `ts` |
| 0.2.2 WS book diffs | `tests/recorder/test_book_diff_normalize.py` | живого сокета нет | фикстура snapshot+20 диффов; `u` подряд, `seq` дырявый — так у Bybit. Кадр без `type` — ошибка, не тихий delta |
| 0.2.3 реконструктор | `tests/book/test_bit_identical.py` | не нужно | два прогона = один fingerprint; ключи `Decimal` — `60000.0` и `60000` один уровень, ноль его снимает |
| 0.2.4 ресинк | `tests/book/test_resync.py` | не нужно | синтетический gap → `stream=resync`; книга = снимок; `BybitBookWs` с `fetch_snapshot` тоже; без fetch — `BookDirty`, глубину не выдумываем |
| 0.2.5 стены | `tests/book/test_wall_watch.py` | не нужно | 50 BTC @ 60000: pull / eaten. Это не вход |
| 0.2.6 альты | `infra/universe.week0.yaml` = BTC+ETH; `tests/screener/test_universe.py` | нет суток BTC | файл и валидатор есть (200 монет / HTX / без ETH — отказ). Альты **не** дописаны. Live — **не зелёный** |
| 0.2.7 Nautilus replay | `ReplayEngine.run` + `tape`; `tests/exec/test_replay_bit_identical.py` | нет записанного дня | два прогона книги = те же `best()`. Лента 5 сделок из `trades.jsonl`; нет файла — пусто, не выдумка. Полный день VPS — **нет**. Nautilus не тянули |
| 0.2.8 PIT SQL | `tests/storage/test_pit_query.py` | не нужно | DuckDB по уже видимым строкам; срез 12:00 не видит 12:05; `enable_external_access=false` без тихого pass |

Неделя 1 **не закрыта**. Стратегию отскока не пишем.

Факты Bybit, не догадки:
- сборка книги — `u` (подряд); `seq` — кросс-номер. [orderbook REST](https://bybit-exchange.github.io/docs/v5/market/orderbook), [WS](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- `cts` книги стыкуется с `T` сделки; `ts` — системное время, в официальном REST-примере на 126 мс позже
- `publicTrade.seq` может повторяться в нескольких сообщениях. [trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)

Вселенная недели 0 по канону PHASE-BUILD: `symbols: [BTCUSDT, ETHUSDT]`. 8–15 альтов — после 0.1.7, не список «с потолка».

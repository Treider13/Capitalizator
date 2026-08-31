# Статус шагов (честно)

Дата проверки: 2026-08-31.

| Шаг | Код / тест | Живое железо | Итог |
|---|---|---|---|
| −1.1 каркас | pytest `tests/test_import.py` | не нужно | зелёный после прогона |
| −1.2 замки | ruff + gitleaks-конфиг + хук | хук ставит человек | конфиг есть; хук не установлен в этом облаке автоматически |
| −1.3 нет доливки | `tests/risk/test_no_average.py` | не нужно | зелёный после прогона |
| −1.4 PIT | `tests/test_pit.py` | не нужно | зелёный после прогона |
| 0.1.1 VPS SG/TYO | — | нет | **не зелёный** |
| 0.1.2 ключи | чеклист-шаблон | нет | **не зелёный** |
| 0.1.3 docker healthz | `tests/recorder/test_app.py` | docker на VPS нет | код зелёный; compose на VPS — нет |
| 0.1.4 WS час BTC | 100 мок-сделок | живой час нет | нормализация зелёная; час записи — **нет** |
| 0.1.5 parquet | `tests/recorder/test_parquet_sink.py` | не нужно | зелёный после прогона |
| 0.1.6 gap | `tests/recorder/test_gap.py` | не нужно | зелёный после прогона |
| 0.1.7 сутки | — | нет | **не зелёный** |
| 0.2.1 REST snapshot | `tests/recorder/test_snapshot.py` | curl с VPS нет | парсер по официальному примеру Bybit; живой fetch — skip если нет сети |
| 0.2.2 WS book diffs | `tests/recorder/test_book_diff_normalize.py` | живого сокета нет | фикстура snapshot+20 диффов; `u` подряд, `seq` дырявый — так у Bybit |
| 0.2.3 реконструктор | `tests/book/test_bit_identical.py` | не нужно | два прогона = один fingerprint; ноль удаляет уровень |
| 0.2.4 ресинк | `tests/book/test_resync.py` | не нужно | синтетический gap → `stream=resync`; книга = снимок, яд диффа не кладётся сверху |
| 0.2.5 стены | `tests/book/test_wall_watch.py` | не нужно | 50 BTC @ 60000: pull / eaten. Это не вход |
| 0.2.6 альты | — | нет суток BTC | **не начинали** |
| 0.2.7 Nautilus replay | — | нет записанного дня | **не начинали** |

Неделя 1 **не закрыта**. Стратегию отскока не пишем.

Факт по Bybit, не догадка: для сборки книги смотрим `u` (подряд). Поле `seq` — кросс-номер, дырки в нём нормальны. Источник: [Get Orderbook](https://bybit-exchange.github.io/docs/v5/market/orderbook) и [WS orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook).

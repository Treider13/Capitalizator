# STATUS (сгенерировано)

Дата: 2026-09-03T06:31:03+00:00. Этот файл пишет `python -m capitalizator.ops.gen_status`; руками не редактировать.

- Тесты: **1627 passed, 2 skipped in 32.04s**
- Ruff: **чисто**
- Модулей достижимо из точек входа: **199**; недостижимо: **5**

## Процессы (infra/deploy/compose.yml)

| Процесс | Команда | Что делает |
|---|---|---|
| recorder | `capitalizator.recorder.app --live-ws` | сырой WS Bybit: сделки, дельты книги, тикеры (OI/фандинг), ликвидации → jsonl (живой) + parquet (архив); instruments-info раз в час |
| desk | `capitalizator.desk --serve` | зоны → касание → CAV/ZLG (выжившая ликвидность)/PRS → ОКО → жюри (факт книги обязателен) → бумага → интент |
| signer | `capitalizator.signer --serve` | единственный с ключом: pybit, липкий блок входов, сторож по эпизодам, сверка REST без усыновления, unknown→resolve |
| intel | `capitalizator.intel --serve` | RSS/Reddit/X/Hyperliquid/Bybit public/F&G → knowledge; LLM-экстрактор по схеме; резолюция авторов на своей ленте |
| console | `capitalizator.ops.console --serve` | 127.0.0.1:8082: стол, настройки (ключи/источники), словарь кодов |
| night | shell-цикл | ночной контур 00:30 UTC, компакция ленты каждый час |

## Недостижимые из рантайма модули

- `capitalizator.exec.breakout_gesture`
- `capitalizator.news_macro.sentiment`
- `capitalizator.patterns.exam`
- `capitalizator.recorder.rest_ticker`
- `capitalizator.risk.nmin`

## Что по замыслу выдаёт «нет данных», пока не набрана статистика

- веса жюри и голоса меток — n_min (20) на класс; паспорт ОКО — mature_n (30) на символ;
- прогноз/память ОКО — n_min окон в классе; калибровка классов — mature_n бумажных сделок;
- веса авторов — ≥5 разрешённых вызовов; месячный сентимент — ≥20 дневных отпечатков.
Это не заглушки: функции работают и показывают, сколько набрано из скольких.

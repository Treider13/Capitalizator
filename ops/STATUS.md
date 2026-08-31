# Статус шагов (честно)

Дата проверки: 2026-08-31. Локально: прогон после гейта Ф1 и карточки — см. число после pytest. Skip = нет egress на `api.bybit.com`. GitHub Actions на ветке — **startup_failure**. Это не «CI зелёный».

| Шаг | Код / тест | Живое железо | Итог |
|---|---|---|---|
| −1.1 каркас | pytest `tests/test_import.py` | не нужно | зелёный после прогона |
| −1.2 замки | ruff + gitleaks-конфиг + `.github/workflows/lint.yml` | хук и Actions включает человек | конфиг и workflow-файл есть. gitleaks без бинаря = skip, не тихий pass. GH Actions **startup_failure** — не зелёный |
| −1.3 нет доливки | `tests/risk/test_no_average.py` | не нужно | зелёный после прогона |
| −1.4 PIT | `tests/test_pit.py` | не нужно | зелёный после прогона |
| 0.1.1 VPS SG/TYO | — | нет | **не зелёный** |
| 0.1.2 ключи | `ops/key-checklist.md` шаблон без значений | галочки человек не ставил | шаблон есть; **не зелёный** |
| 0.1.3 docker healthz | `tests/recorder/test_app.py`, `tests/infra/test_recorder_docker.py` | docker на VPS нет | Dockerfile/compose без ключей; compose up на VPS — **нет** |
| 0.1.4 WS час BTC | `BybitTradesWs.run()` + `--from-jsonl`; p50/p95 `recv-exchange` в JSON | живой час нет | ack не сделка. `--minutes` без jsonl — отказ. Час записи — **нет** |
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
| 0.3.1 зоны | `tests/zones/test_no_lookahead.py`, `test_double_run.py` | не нужно | `prior_day_hl` + свинг; бар t+1 не создаёт зону до t; `zone_id` = blake2s. ICT/FVG нет |
| 0.3.2 HTF | `tests/zones/test_htf_bias.py` | не нужно | long/short/box/unknown по закрытым 4h; будущий бар не переворачивает срез |
| CAV запись | `tests/patterns/test_cav.py` | не нужно | REJECT/THROUGH/COMPRESS/DRIFT/NOISE на закрытой свече. Не вход |
| registry | `infra/registry.yaml` | не нужно | числа из PHASE-BUILD; лишний ключ — отказ |
| 0.3.3 касания | `tests/memory/test_touch_outcome.py` | нет живого часа | pending→bounce/break/die; чужой символ с той же ценой — не касание. Live-ленты нет |
| 0.3.4 лента/OFI | `tests/tape/test_classify.py`, `test_eaten.py`, `test_ofi.py` | нет живого часа | taker = поле side; eaten = ≥50% `depth_near` за 8 с; OFI = CKS `e_n`, не CVD. Поле без книги не заполняем |
| 0.3.5 PRS | `tests/prs/test_tau.py` | не нужно | известный τ=3 с; цензура 8 с; два прогона → тот же Y. `place_order` в `prs/` нет |
| 0.3.6 ZLG | `tests/zlg/test_labels.py`, `test_double_run.py` | не нужно | 5 меток; SILENCE если max A < γ·q. Два прогона = одна метка. Размер не открывается |
| 0.3.7 BTC-режим | `tests/btc/test_regime.py` | не нужно | trend/box с закрытого HTF; news только с `known_at ≤ t`; unknown → None. `veto()` нет |
| 0.3.8 отчёт | `tests/ops/test_daily_report_no_advice.py` | не нужно | касания/жесты/дыры/пинг; «лонг/купи/завтра» — ошибка |

| 0.4.1 новости | `tests/news/test_pit.py` | не нужно | CSV BLS/Fed: CPI 11 Sep / 14 Oct / 10 Nov (EST 13:30Z); FOMC 16 Sep / 28 Oct. Срез до `known_at` пустой. TG нет |
| 0.4.7 комиссии | `tests/exec/test_fees.py` | не нужно | VIP0 0.0002/0.00055 ×2; +1R после комиссий меньше на известную величину. Fill по печати, не close |
| 0.4.8 дрейф | `tests/champion/test_drift_synthetic.py` | не нужно | Page-Hinkley: 0.3→0.7 = drift; плоский 0.3 — нет. Не live |
| 0.4.9 hashlog | `tests/memory/test_hashlog.py` | не нужно | касание пишет звено; жест — следующее; подмена ломает verify; `episode` пустой |
| 0.4.3 сводка | `tests/llm/test_no_egress.py`, `test_no_advice.py` | контейнера нет | яд «купи» → `trade_advice=false`; TCP connect в sandbox — ошибка. Модель по сети не вызываем |
| 0.4.4 signer схема | `tests/signer/test_schema.py` | ключа/тестнета нет | validate: week0 + stop + testnet. Mainnet/SOL — отказ. Ордер не шлём. Ключ не читаем |
| 0.4.2 авторы | `tests/authors/test_ingest.py` | нет 20 постов | jsonl без `weight`; TG запрещён; `check_author_raw --min 20` = код 2. Посты не выдумывал |
| 0.4.5 dead-man | `tests/signer/test_deadman.py` | тестнета нет | тишина >30 с → `cancel_all` (колбэк). Не биржа |
| 0.4.6 reconcile | `tests/signer/test_reconcile.py` | тестнета нет | `tick({})` снимает локальный ордер. Мок, не сайт |
| 0.4.10 гейт Ф0 | `tests/ops/test_gate_f0.py` | нет 30 суток | `gates f0` код 2. `infra/phase.yaml` phase=0, trading_mode=off. Файл не переключаем |

| 1.5.1 размер | `tests/risk/test_sizing.py`, `test_alt_wide_stop.py` | не нужно | `Sizing.compute(100000, 3, 0.02, 0.01)` → отказ (16.67% > 10%). 20%×5×4% = 4% при target 1.2% → отказ **из-за риска**, не только из-за капа 3x. Ордера нет |
| 1.5.2 краны | `tests/risk/test_halts.py` | не нужно | `Halts.state`; день −3% / неделя −6% / пик −25% / liq. После liq reason не переписывается. Flatten — `RiskEngine.on_flat`, не этот класс |
| 1.5.3 одна позиция | `tests/risk/test_one_position.py` | не нужно | `RiskEngine._open_position: Position \| None`. Второй вход reject. `PositionBook` убран — второй счётчик врал бы |
| 1.5.4 сессия | `tests/risk/test_session.py`, `test_us_data_day.py` | не нужно | 12:00Z reject, 14:10Z accept, 20:00Z reject; ночь 5x всегда reject. Окно из `infra/time.yaml` + `zoneinfo`. CPI 11 Sep / 10 Nov (EST) / FOMC 16 Sep до 13:30Z = `us_data_day`. 24ч-кат **не** включён (2.11.7) |
| 1.5.5 demo adapter | `tests/exec/test_demo_mode_no_mainnet.py` | hello нет | `trading_mode=off` → отказ. Инжект `demo` → `{mode: demo, status: not_sent}`. Host mainnet в `exec/`+`signer/` нет. **Hello лимит+cancel на демо — нет** (ключа/тестнета нет) |
| 1.5.6 стоп | `tests/signer/test_stop_required.py` | биржа нет | нет `stop_px` → ValidationError; ноль → ValueError. HTTP 4xx нет — процесса signer нет. Ордер не шлём |

| 1.6.1 отскок | `tests/exec/test_bounce_gates.py` | ордера нет | `propose` смотрит `phase.yaml` **и** снимок. Сейчас phase=off → None даже если в снимке demo. Инжект `desk_mode=demo` только в тестах. Шорт с resistance; next zone <1.5R → None. `submit` нет |
| 1.6.2 середина | `tests/exec/test_mid_range.py` | не нужно | цена ровно между support.hi и resistance.lo → None |
| 1.6.3 50% / трейл | `tests/exec/test_partial_1r.py`, `test_no_mechanical_be.py` | не нужно | +1R → reduce 50%; +2R остаток жив; стоп → flatten без доливки. `move_to_be_at_pct` в исходнике нет. +2% цены при стопе 4% ≠ БУ |
| 1.6.4 скринер | `tests/screener/test_spread.py` | не нужно | спред 0.4% при ходе 0.3% → отказ. SOL не из week0 → отказ. ATR не выдумываем |
| 1.6.5 лимит | `tests/exec/test_maker_only_f1.py` | не нужно | `TAKER_OK=false`, `ORDER_TYPE=limit` |
| 1.6.6 episode | `tests/exec/test_episodes.py`, `tests/ops/test_day_episodes.py` | нет демо-входов | лог пустой; `day_episodes` без файла → n=0. mode=live отказ |

| 1.7.1 карточка | `tests/card/test_require_card.py`, `test_card_before_intent.py` | нет живых карточек | `propose` по умолчанию требует файл. Нет файла → None. Фикстура unit, не рынок |
| 1.7.2 костыль | `tests/verifier/test_manual_bind.py` | не SQL на проде | «23 из 31» без файла запроса → UNVERIFIABLE. Совпадение файла = VERIFIED |
| 1.7.3 first_fact | `tests/card/test_first_fact_no_sizeup.py` | n жестов <20 | n=19 / SILENCE → `shadow_gesture`, `size_mult=1`. n=20 не увеличивает лот |
| 1.7.4 1–3/день | `tests/risk/test_max_three.py` | не нужно | 4-й `propose` → None |
| 1.7.5 тень ширины | `tests/champion/test_no_auto_promote.py` | ордеров нет | отчёт 0.8 и 1.2; `promote()` отказ; чемпион не сменён |
| 1.8.1 skip | `tests/ops/test_check_skips.py` | недели сессии нет | нет файла → n=0, код 2. Не рисуем «зелёную неделю скипов» |
| 1.8.2 TCA | `tests/exec/test_tca_table.py` | нет демо-fill | пустая таблица → медиана `None`, не ноль. Два слипа 1 и 3 тика → медиана 2 |
| 1.8.3 avg R | `ops/gate_f1.sql` | нет 80 демо | SQL есть; строк episode нет. avg_r не выдумываем |
| 1.8.4 гейт Ф1 | `tests/ops/test_gate_f1.py` | нет 80 демо | `gates f1` код 2. G1.1/G1.2 красные. G1.3–G1.5 (схема/zlg/breakout) зелёные. `phase.yaml` не трогаем |

Неделя 1 **не закрыта** (нет VPS/суток). Гейт Ф0 красный. `trading_mode=off`. Код 1.6–1.7 на ветке, **ордеров нет**, hello демо красный. Не «всё реализовано».

Чужие проекты / форумы (не копировали стратегии):
- Freqtrade: Bybit **futures isolated** умеет stoploss on exchange; Bybit **spot** — нет. Мы linear perp, стоп обязателен в схеме, на биржу не слали.
- Elite Trader Turok (2001): не угадывать bounce/break заранее. У нас вход только при цене в зоне и закрытой логике CAV на журнале; жест не открывает размер.
- NFI / passivbot / OctoBot grid — доливка. Это антипример, `average_in` по-прежнему отказ.

Факты Bybit, не догадки:
- сборка книги — `u` (подряд); `seq` — кросс-номер. [orderbook REST](https://bybit-exchange.github.io/docs/v5/market/orderbook), [WS](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- `cts` книги стыкуется с `T` сделки; `ts` — системное время, в официальном REST-примере на 126 мс позже
- `publicTrade.seq` может повторяться в нескольких сообщениях. [trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)

Вселенная недели 0 по канону PHASE-BUILD: `symbols: [BTCUSDT, ETHUSDT]`. 8–15 альтов — после 0.1.7, не список «с потолка».

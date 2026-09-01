# Статус шагов (честно)

Дата проверки: 2026-09-01. Локально: **826 passed, 2 skipped** (skip = нет egress на `api.bybit.com`; нет бинаря gitleaks). GitHub Actions на ветке — **startup_failure**. Это не «CI зелёный».

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
| 0.1.5 parquet | `tests/recorder/test_parquet_sink.py` | не нужно | запись и `.lock` через `dir_fd` (`openat`); `S_ISREG`; два писателя — flock + перечит. Счётчик — `metadata.num_rows` через fd. Зелёный после прогона |
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
| CAV запись | `tests/patterns/test_cav.py`, `test_bar_quality.py`, `test_width.py`, `test_exam.py` | не нужно | REJECT/THROUGH/COMPRESS/DRIFT/NOISE на закрытой свече. stagnant/illiquid → NOISE; разрыв режет ATR. `w_now`/`w_rank`/`session_hour` — журнал, не вход |
| registry | `infra/registry.yaml` | не нужно | числа из PHASE-BUILD; лишний ключ — отказ |
| 0.3.3 касания | `tests/memory/test_touch_outcome.py` | нет живого часа | pending→bounce/break/die; чужой символ с той же ценой — не касание. Live-ленты нет |
| 0.3.4 лента/OFI | `tests/tape/test_classify.py`, `test_eaten.py`, `test_ofi.py` | нет живого часа | taker = поле side; eaten = ≥50% `depth_near` за 8 с; OFI = CKS `e_n`, не CVD. Поле без книги не заполняем |
| 0.3.5 PRS | `tests/prs/test_tau.py` | не нужно | известный τ=3 с; цензура 8 с; два прогона → тот же Y. `place_order` в `prs/` нет |
| 0.3.6 ZLG | `tests/zlg/test_labels.py`, `test_double_run.py` | не нужно | 5 меток; SILENCE если max A < γ·q. Два прогона = одна метка. Размер не открывается |
| 0.3.7 BTC-режим | `tests/btc/test_regime.py` | не нужно | trend/box с закрытого HTF; news только с `known_at ≤ t`; unknown → None. `veto()` нет |
| 0.3.8 отчёт | `tests/ops/test_daily_report_no_advice.py` | не нужно | касания/жесты/дыры/пинг; «лонг/купи/завтра» — ошибка |
| знания / бэкап | `tests/ops/test_vault_backup.py` | VPS нет | Snapshot: serialize + `VACUUM`. DB: `openat` + `/proc/self/fd`; `secure_delete`. nlink на fd. Staging — `mkdirat`/`renameat`. `write_all`. `0o600`. Иголки по байтам: ASCII без регистра + UTF-16 LE/BE (факт: UTF-16LE и `bybit_api_key=` уезжали). Base64 не декодируем. Симлинк / FIFO / hardlink / секрет — отказ. Живого диска VPS **нет** |
| консоль ноут | `tests/ops/test_console.py` | туннеля нет | GET `/` и `/api/status`; POST/PUT/DELETE/PATCH 405; только 127.0.0.1. Без LAYOUT не встаёт. Поля `vps` нет. Симлинк `desk.sqlite` / `tape/` — отказ, 500 `error`. Пустой `desk.sqlite` не дописывает схему. Signer не импортирован |

| 0.4.1 новости | `tests/news/test_pit.py` | не нужно | CSV BLS/Fed/BEA: CPI + FOMC + NFP (4 Sep / 2 Oct / 6 Nov EST / 4 Dec EST) + PCE (30 Sep / 29 Oct / 25 Nov EST / 23 Dec EST). Срез до `known_at` пустой. NFP/PCE не в MacroRules 24ч/ET. TG нет |
| 0.4.7 комиссии | `tests/exec/test_fees.py` | не нужно | VIP0 0.0002/0.00055 ×2; +1R после комиссий меньше на известную величину. Fill по печати, не close |
| 0.4.8 дрейф | `tests/champion/test_drift_synthetic.py` | не нужно | Page-Hinkley: 0.3→0.7 = drift; плоский 0.3 — нет. Не live |
| 0.4.9 hashlog | `tests/memory/test_hashlog.py` | не нужно | касание пишет звено; жест — следующее; подмена ломает verify; `episode` пустой |
| 0.4.3 сводка | `tests/llm/test_no_egress.py`, `test_no_advice.py` | контейнера нет | яд «купи» → `trade_advice=false`; TCP connect в sandbox — ошибка. Модель по сети не вызываем |
| 0.4.4 signer схема | `tests/signer/test_schema.py` | ключа/тестнета нет | validate: week0 + stop + testnet. Mainnet/SOL — отказ. Ордер не шлём. Ключ не читаем |
| 0.4.2 авторы | `tests/authors/test_ingest.py` | нет 20 постов | jsonl без `weight`; TG запрещён; `check_author_raw --min 20` = код 2. Посты не выдумывал |
| 0.4.5 dead-man | `tests/signer/test_deadman.py` | тестнета нет | тишина >30 с → `cancel_all` (колбэк). Не биржа |
| 0.4.6 reconcile | `tests/signer/test_reconcile.py` | тестнета нет | `tick({})` снимает локальный ордер. Позиция без локальной идеи → CRITICAL, flatten не шлём. Мок, не сайт |
| 0.4.10 гейт Ф0 | `tests/ops/test_gate_f0.py` | нет 30 суток | `gates f0` код 2. `infra/phase.yaml` phase=0, trading_mode=off. Файл не переключаем |

| 1.5.1 размер | `tests/risk/test_sizing.py`, `test_alt_wide_stop.py` | не нужно | `Sizing.compute(100000, 3, 0.02, 0.01)` → отказ (16.67% > 10%). 20%×5×4% = 4% при target 1.2% → отказ **из-за риска**, не только из-за капа 3x. Ордера нет |
| 1.5.2 краны | `tests/risk/test_halts.py` | не нужно | `Halts.state`; день −3% / неделя −6% / пик −25% / liq. После liq reason не переписывается. Flatten — `RiskEngine.on_flat`, не этот класс |
| 1.5.3 одна позиция | `tests/risk/test_one_position.py` | не нужно | `RiskEngine._open_position: Position \| None`. Второй вход reject. `PositionBook` убран — второй счётчик врал бы |
| 1.5.4 сессия | `tests/risk/test_session.py`, `test_us_data_day.py` | не нужно | 12:00Z reject, 14:10Z accept, 20:00Z reject; ночь 5x всегда reject. Окно из `infra/time.yaml` + `zoneinfo`. CPI / FOMC / NFP 4 Sep и 6 Nov EST / PCE до сессии = `us_data_day`. 24ч-кат **не** включён (2.11.7) |
| 1.5.5 demo adapter | `tests/exec/test_demo_mode_no_mainnet.py` | hello нет | `trading_mode=off` → отказ. Инжект `demo` → `{mode: demo, status: not_sent}`. Host mainnet в `exec/`+`signer/` нет. **Hello лимит+cancel на демо — нет** (ключа/тестнета нет) |
| 1.5.6 стоп | `tests/signer/test_stop_required.py` | биржа нет | нет `stop_px` → ValidationError; ноль → ValueError. HTTP 4xx нет — процесса signer нет. Ордер не шлём |

| 1.6.1 отскок | `tests/exec/test_bounce_gates.py` | ордера нет | `propose` смотрит `phase.yaml` **и** снимок. Сейчас phase=off → None даже если в снимке demo. Инжект `desk_mode=demo` только в тестах. Шорт с resistance; next zone <1.5R → None. `submit` нет |
| 1.6.2 середина | `tests/exec/test_mid_range.py` | не нужно | цена ровно между support.hi и resistance.lo → None |
| 1.6.3 50% / трейл | `tests/exec/test_partial_1r.py`, `test_no_mechanical_be.py` | не нужно | +1R → reduce 50%; +2R остаток жив; стоп → flatten без доливки. `move_to_be_at_pct` в исходнике нет. +2% цены при стопе 4% ≠ БУ |
| 1.6.4 скринер | `tests/screener/test_spread.py` | не нужно | спред 0.4% при ходе 0.3% → отказ. SOL не из week0 → отказ. ATR не выдумываем |
| 1.6.5 лимит | `tests/exec/test_maker_only_f1.py` | не нужно | `TAKER_OK=false`, `ORDER_TYPE=limit` |
| 1.6.6 episode | `tests/exec/test_episodes.py`, `tests/ops/test_day_episodes.py` | нет демо-входов | лог пустой; `day_episodes` без файла → n=0. mode=live отказ |

| 1.7.1 карточка | `tests/card/test_require_card.py`, `test_card_before_intent.py` | нет живых карточек | `propose` требует файл **и** несущий VERIFIED после `ManualVerifier.bind`. VERIFIED в JSON файла → отказ. pending-файл один → None |
| 1.7.2 костыль | `tests/verifier/test_manual_bind.py`, `tests/card/test_load_bearing.py` | не SQL на проде | `BindReceipt`. Сырое `"VERIFIED"` — отказ. Нет файла / подмена текста после bind — отказ. «23 из 31» без файла → UNVERIFIABLE |
| 1.7.3 first_fact | `tests/card/test_first_fact_no_sizeup.py`, `test_first_fact_argmin.py` | n жестов <20 | n=19 / SILENCE → тень, `size_mult=1`. `pick_by_horizon`: 8s бьёт 1d только при n≥20. Поле `first_fact` в JSON карточки — отказ (extra=forbid). Не Ф2-вход |
| 1.7.4 1–3/день | `tests/risk/test_max_three.py` | не нужно | 4-й `propose` → None |
| 1.7.5 тень ширины | `tests/champion/test_no_auto_promote.py` | ордеров нет | отчёт 0.8 и 1.2; `promote()` отказ; чемпион не сменён |
| 1.8.1 skip | `tests/ops/test_check_skips.py` | недели сессии нет | нет файла → n=0, код 2. Не рисуем «зелёную неделю скипов» |
| 1.8.2 TCA | `tests/exec/test_tca_table.py` | нет демо-fill | пустая таблица → медиана `None`, не ноль. Два слипа 1 и 3 тика → медиана 2 |
| 1.8.3 avg R | `ops/gate_f1.sql` | нет 80 демо | SQL есть; строк episode нет. avg_r не выдумываем |
| 1.8.4 гейт Ф1 | `tests/ops/test_gate_f1.py` | нет 80 демо | `gates f1` код 2. Считаются только closed demo bounce с fill_qty>0. Пустой dict не строка. G1.3 = `average_in` в FORBIDDEN, не grep. `phase.yaml` не трогаем |

| PTF бумага | `tests/champion/test_ptf.py` | нет живых классов | ρ = E[R]×риск%/часы. n=19 → ρ=`None`; n=138 не pickable; часы≤0 или >3 отказ; ρ≤0 не pickable; риск>1% без гейта отказ; `world_return_rank()` всегда `None` |
| WJD бумага | `tests/jury/test_desk.py`, `test_weights.py`, `tests/memory/test_stamp_jury.py` | нет живых меток | THROUGH×DEFEND = SPLIT. Вес = n/(n+20)×hit только после экзамена; до n=20 веса равны. `weight_opens_size` всегда false. `propose` жюри не читает |
| saved-R бумага | `tests/memory/test_saved_r.py` | нет живых скипов с исходом | пустой итог `None`, не ноль. skip bounce → later break = +1R; later bounce = missed, не прибыль. Чужая причина — отказ. Не PnL |
| LLM не ставит вердикт | `tests/llm/test_cannot_verify.py`, `test_redteam_poison.py` | контейнера нет | яд `verdict=VERIFIED` / `API_KEY` не копируется в сводку. `trade_advice=false`. Сокет в sandbox — ошибка. Не модель по сети |
| 2.9.1 зоны BTC | `tests/btc/test_zones.py` | нет живой карты | тот же `ZoneEngine`, не второй движок. Есть support/resistance и regime=box на закрытых 4h. У `BtcRegime` метода `veto()` нет |
| 2.9.2 слом | `tests/btc/test_break_definition.py` | нет живого часа | фитиль ниже поддержки / выше сопротивления ≠ слом. Закрытие за зоной + eaten = слом. ETH не слом BTC |
| 2.9.3 вето альт | `tests/btc/test_veto_alt.py` | не в `propose` | SOL long + слом поддержки → `allow=False`. Шорт + вынос сопротивления → False. Та же сторона не режется. `strategy_bounce` **не импортирует** BtcVeto |
| 2.9.5 тень вето | `tests/champion/test_veto_shadow.py` | ордеров нет | отчёт veto on/off; `promote()` отказ |
| 2.10.1 eaten | `tests/exec/test_bounce_eaten.py` | флаг выкл | `check_tape` по умолчанию False. При True: eaten или **нет данных** → None (не выдумываем «не ели») |
| 2.10.2 стена | `tests/exec/test_wall_no_print.py` | флаг выкл | `check_wall` по умолчанию False. При True: стена без печати или **неизвестно** → None |
| 2.11.7 макро | `tests/news/test_macro_rules.py` | не в Session | выкл → size 1. Вкл: 10 Sep 14:10Z за 24ч до CPI → ×0.5; 9 Sep → 1; FOMC/CPI 14:10 ET → `et_blackout`. 9 Dec EST: 18:10Z ещё pre, 19:10Z закрыто. Session 10 Sep всё ещё open |
| 2.12.5 сентимент | `tests/news/test_sentiment_derisk.py` | нет индекса | месяц + жадность → reject. Час → reject (не «купи страх»). Не шорт «потому что все купили» |
| флаги фазы | `tests/ops/test_phase_flags.py` | не нужно | `trading_mode` и `equity_source` — **строки** `"off"`/`"none"`. Голый YAML `off` = False; это дыра, файл в кавычках |
| 2.10.3 PRS | `tests/risk/test_prs_cut.py` | порог не в yaml | Y выше порога → reject. Y=`None` (мало n) ≠ тонкая книга. Порог — аргумент, `registry.yaml` не трогали |
| 2.12.2 hit/miss | `tests/authors/test_resolve.py` | нет 50 постов | после горизонта up+1% = hit. До горизонта hit пустой. Повторная сверка — отказ |
| 2.12.3 вес | `tests/authors/test_shrinkage.py` | нет журнала | 1/1 и 4/4 = 0. 0/20 = 0. 10/20 = формула |
| 2.12.4 не accept | `tests/authors/test_no_entry.py` | не нужно | автор никогда не accept. `propose` без зоны → None |
| 2.11.1 схема | `tests/card/test_schema.py` | не нужно | битый JSON / нет `known_at` / голый текст — не карточка |
| 2.11.2 SQL PIT | `tests/verifier/test_recompute.py` | нет прод-SQL | «23 из 31» = два числа из запроса. «24 из 31» тем же SQL → REFUTED. Срез 12:10 не видит 23. VERIFIED без файла результата не штампует карточку |
| 2.12.1 parse | `tests/authors/test_parse.py` | нет 50 постов | `AuthorParse` только если уже есть claims+horizon+known_at. Текст «BTC long» без полей → не разобран. `check_author_parsed --min 50` = код 2. Посты не выдумывал |
| 3.13.1 флаг | `tests/exec/test_breakout_flag.py` | Г2 красный | `breakout_enabled()` читает **bool**. Строка `"false"` — не выкл. Класса `BreakoutStrategy` нет. `propose` его не зовёт |
| 3.13.2 первая минута | `tests/exec/test_first_minute.py` | пробоя нет | `FirstMinute` из `time.yaml` (60 с). 0–59 с после close → block; 60 с → нет. `strategy_bounce` **не импортирует** FirstMinute |
| 3.14.1 анлоки | `tests/screener/test_unlock.py` | нет Tokenomist | `infra/calendars/unlocks.csv` — только заголовок. Нет файла → пусто, не выдумка. Команда сегодня/завтра → скринер. Инвестор не режет. Не шорт |
| гейт Ф2 бумага | `tests/ops/test_gate_f2.py` | нет 50 карточек | `gates f2` код 2. Пустые эпизоды ≠ «0 против BTC». CI красной команды **не** зелёный (`G2.6_redteam_ci=false`) |
| пороги yaml | `tests/ops/test_gates_yaml.py` | не нужно | `infra/gates.yaml` как в PHASE-BUILD. Лишний ключ — отказ. `bounce_slack_r=0.15` записан **до** Ф3, не после прогона |
| гейт Ф3 бумага | `tests/ops/test_gate_f3.py` | нет 40 пробоев | `gates f3` код 2. Пусто ≠ 40. 40 `failed_break` ≠ пробой. 100 отскоков без пробоя ≠ Г3. Сквиз без таблицы ≠ допуск. `phase.yaml` не трогаем |
| гейт Ф4 бумага | `tests/ops/test_gate_f4.py` | нет микро | `gates f4` код 2. 80 за 3 недели ≠ «что позже». 8 недель и 40 ≠ 100. Пусто ≠ 0 против BTC |
| f5kill бумага | `tests/ops/test_gate_f5kill.py` | нет main PnL | код 2. День −3% не выдумываем. `target_risk>0.012` → код 3. `phase.yaml` не пишет |
| 3.13.4 фейк-тег | `tests/exec/test_failed_break_tag.py` | не вход | фитиль за зоной + close внутри → `failed_break`. Close за зоной ≠ этот тег. `propose` не импортирует. В счётчик bounce/breakout не входит |
| 3.14.3 REFUTED | `tests/exec/test_refute_flatten.py` | нет mid-trade | несущий REFUTED → flatten. UNVERIFIABLE / pending / не несущее → не выход |
| 3.14.2 реакция | `tests/news/test_reaction_prior.py` | нет наших n | CSV — заголовок. n<5 → coef `None`. `opens_size` всегда false. Числа из intelligence-layer не копировал |
| 3.15.1 PIT кит | `tests/whales/test_pit.py` | нет HL | нет файла → пусто. `accept()` false. `signal`/`weight`/`side` — отказ. `hl_ingest.py` нет |
| 3.15.4 кит | `tests/whales/test_no_single_wallet.py` | нет HL | `whale_accepts` всегда false. Один claim whale → sole. `hl_ingest.py` нет. `propose` китов не импортирует |
| 4.17.1 тень бумага | `tests/exec/test_shadow_no_signer.py` | Г3 красный | `ShadowWriter` → `sent=false`. Signer не импортирован. `trading_mode` не shadow |
| 5.24 урок | `tests/llm/test_lesson_no_average.py` | контейнера нет | «долей» / `average_in` → не совет и не слово в сводке |
| yaml-часы | `tests/signer/test_deadman.py`, `test_reconcile.py` | тестнета нет | `dead_man_s=30` и `reconcile_s=60` из `time.yaml`, не магические числа в стороне |
| счётчики гейта | `tests/ops/test_gates_count_rules.py` | нет 80 демо | 79 bounce ≠ порог. 80 `failed_break` ≠ bounce. Репо `n_bounce=0`. Фикстуры — не живые сделки |
| 3.13.2 close | `tests/exec/test_breakout_close.py` | флаг false | флаг выкл → нет, даже если close+eaten+BTC. Фитиль ≠ close. Первая минута → нет. Файла `strategy_breakout.py` нет |
| 3.13.3 жест | `tests/exec/test_breakout_gesture.py` | не вход | DEFEND после прокола → `fake_defend`. RETREAT не этот skip. `propose` не импортирует |
| 3.15.5 хрупкость | `tests/whales/test_fragility.py` | нет OI | три True → запрет новых лонгов. `None` ≠ пик. Теплокарта не вход. `propose` не импортирует |
| 4.19.2 drift | `tests/risk/test_drift_cut.py` | не live | drift → target 0.005. `phase.yaml` target 0.01 не трогали |
| 4.18.5 n_min | `tests/risk/test_nmin_quarter.py` | не Ф4 | Ф1 size_mult=1 даже при SILENCE. Четверть только если явно `phase=f4` |
| 5.23 A+ | `tests/risk/test_aplus.py` | не Ф5 | 5 ролей + BTC. F1 Sizer 5x всё равно reject. `raises_lev_in_f1` false |
| 5.23 размер Ф5 | `tests/risk/test_f5_sizing.py` | Г4 красный | `f5_target` при `equity_source=none` = `None`. 1.2% только main+Г4. `phase.yaml` target 0.01 не трогали |
| DST 1 Nov | `tests/risk/test_session.py`, `test_macro_rules.py` | не нужно | 2026-11-01 13:30Z = сессия МСК. FOMC 9 Dec (Fed calendar) 14:00 EST = 19:00Z |

Неделя 1 **не закрыта**. Гейты Ф0/Ф1/Ф2/Ф3/Ф4 красные. `trading_mode` читается как строка `"off"`. Макро-правила **не** вшиты в сессию. Ордеров нет. Не «всё реализовано» (нет 20 постов, нет пробоя/китов, нет 50 разобранных авторов, нет живого часа). Не топ мира по %: PTF пустая, `world_return_rank()` = `None`.

Чужие проекты / форумы (не копировали стратегии):
- Freqtrade: Bybit **futures isolated** умеет stoploss on exchange; Bybit **spot** — нет. Мы linear perp, стоп обязателен в схеме, на биржу не слали.
- Elite Trader Turok (2001) / BabyPips: не угадывать bounce/break заранее; первая печать за линией — не сделка; фитиль за уровень + close внутри = фейк, не пробой. У нас это тег `failed_break`, не вход. `FirstMinute` — только пробой, и он выключен.
- NFI / passivbot / OctoBot grid — доливка. Это антипример, `average_in` по-прежнему отказ.
- Census практики: живого bounce-бота с аудированной книгой нет. `propose` — не доказанный край. SMC-библиотеки (lookahead в swing) не копировали.
- Tokenomist / Keyrock (календарь анлоков): команда — самый чувствительный тип; давление часто за ~30 дней до даты; день анлока может быть тихим. Мы **не** шортим «потому что анлок» и **не** подставляли чужие строки. Пустой CSV + флаг скринера.

Факты Bybit, не догадки:
- сборка книги — `u` (подряд); `seq` — кросс-номер. [orderbook REST](https://bybit-exchange.github.io/docs/v5/market/orderbook), [WS](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- `cts` книги стыкуется с `T` сделки; `ts` — системное время, в официальном REST-примере на 126 мс позже
- `publicTrade.seq` может повторяться в нескольких сообщениях. [trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)

Вселенная недели 0 по канону PHASE-BUILD: `symbols: [BTCUSDT, ETHUSDT]`. 8–15 альтов — после 0.1.7, не список «с потолка».

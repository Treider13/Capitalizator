# Аудит предложенных улучшений (6 пунктов)

**Дата:** 2026-09-04.  
**Роль:** архитектурный верификатор Capitalizator.  
**База:** `main` @ `1144d91` и выше. Код не менялся: это сверка предложений из `docs/INDUSTRIAL-RE-2026.md` с фактической цепочкой вызовов.

**Правило:** правка только если усиливает B / C / gateway и не трогает зону, книгу, CAV, жюри, ОКО. Если код уже работает по замыслу — «менять нечего».

---

## Результаты аудита улучшений

### Пункт 1. SL-ack

- **Статус:** Требуется, но с оговорками
- **Обоснование:**

  Цепочка входа уже вешает Mark SL в **том же** `place_order`, а не вторым вызовом после филла (это не Quant Flow):

```377:390:src/capitalizator/gateway/bybit.py
        req = {
            "category": self.category,
            "symbol": symbol,
            "side": "Buy" if side == "buy" else "Sell",
            "orderType": "Limit",
            "qty": str(qty),
            "price": str(entry),
            "timeInForce": "PostOnly",
            "orderLinkId": link,
            "positionIdx": self.position_idx,
            "stopLoss": str(stop),
            "slTriggerBy": "MarkPrice",
            "tpslMode": "Full",
        }
```

  Интент без стопа signer не подписывает (`signer/process.py` 65–73; `tests/signer/test_stop_required.py`).

  После филла подтверждение есть. `PositionTracker` читает `stopLoss` с WS и REST и отдаёт явный предикат:

```312:314:src/capitalizator/gateway/tracker.py
    def stop_confirmed(self, symbol: str) -> bool:
        pos = self.positions.get(symbol)
        return pos is not None and not pos.flat and pos.stop_loss is not None and pos.stop_loss > 0
```

  Signer на каждом reconcile (60 с, `infra/time.yaml` `reconcile_s: 60`, не 5 с) публикует `stop_missing` и делает блок **липким**:

```406:408:src/capitalizator/signer/process.py
        snap["stop_missing"] = [
            s for s in tracker.open_symbols() if not tracker.stop_confirmed(s)
        ]
```

```584:585:src/capitalizator/signer/process.py
            for sym in state.get("stop_missing") or []:
                sticky.setdefault(f"stop_missing:{sym}", when.isoformat())
```

  Закон signer (аудит B1) записан прямо в цикле: блок режет **новые входы**, «never stops or exits» (`signer/process.py` 472–477). Оператор видит баннер (`ops/ops_page.py` 208–209, `ops/i18n_ru.py` 68), Telegram — на смене `entries_blocked`. Тест: `tests/gateway/test_gateway.py` `test_publish_exchange_state_reports_missing_stop_and_fills`.

  Чего нет: ни повторного `set_trading_stop`, ни аварийного flatten. `DeskLoop._sync_exchange_state` читает equity / unknown / venue_flat и **не** смотрит `stop_missing` (`desk/loop.py` 2185–2262). Голая позиция на бирже остаётся, пока человек не нажмёт flatten.

  Копировать Quant Flow (`emergency_close_with_retry` внутри процесса с ключом) **нельзя**: это ломает закон «стол решает, signer исполняет» и даёт ложный flatten на лаге WS (пустое `stopLoss` в первые секунды после филла).

- **Если требуется — точечный план (контур desk + OMS, не ядро A):**

  1. Файл `src/capitalizator/desk/loop.py`, функция `_sync_exchange_state` (уже читает `exchange_state` в demo/live).
  2. После блока venue_flat:
     - если `symbol in state["stop_missing"]` и есть открытый demo-twin (`paper.open_for(symbol, source="demo")` с `filled_at`);
     - **шаг 1:** `self._oms(twin, "amend_stop", now, stop=str(twin.stop), reason="sl_unconfirmed")` — стоп уже есть на двойнике (`exec/paper.py` `PaperPosition.stop`);
     - **шаг 2:** если символ всё ещё в `stop_missing` дольше одного reconcile (грация ≥ `RECONCILE_S` = 60 с, хранить `self._sl_missing_since[symbol]`) — `self._oms(twin, "flatten", now, reason="sl_unconfirmed")` + `paper.flatten(..., reason="sl_unconfirmed")`.
  3. Signer **не** трогать: он уже исполняет OMS даже при заблокированных входах (`drain_oms` перед `drain_validated`, строки 605–606). Gateway `flatten` / `amend_stop` уже есть (`gateway/bybit.py` 463–541). Хронос: событие в journal/meta (`event: sl_unconfirmed`) плюс уже существующий `_record("flatten", ...)` на гейтвее.
  4. Не делать таймер 5 с в signer и не flatten-ить с первого тика.
  5. Тесты, которые затронутся / которые добавить:
     - `tests/gateway/test_gateway.py` — текущий `stop_missing` не ломать;
     - `tests/desk/test_exchange_sync.py` — новый кейс по образцу `test_b_veto_flattens_the_live_twin_and_queues_venue_flatten`: REST позиция без `stopLoss` → сначала `amend_stop` в `oms_rows()`, после грации — `flatten` с `reason=sl_unconfirmed`;
     - `tests/signer/test_process.py` / цикл signer — signer по-прежнему не выходит сам.
  6. Эффект: закрывается дыра «запрос ушёл, биржа не подтвердила» без голоса жюри и без ключа в desk.

---

### Пункт 2. Тень отвергнутых

- **Статус:** Уже реализовано
- **Обоснование:**

  Новая таблица `rejected_touches` **не нужна**. Каждый закрытый рабочий бар с касанием уже пишет полный журнал, в том числе отказы жюри / ОКО / B:

  - `skip_reason`, `jury`, `bearing_verdict`, `b_gate`, `oko_voice` / `oko_reason`, `shadow_would`, `has_tvh` — `desk/loop.py` 1638–1862, колонки `memory/journal.py` 47–66.
  - Закон D-18: B **не останавливает** разметку; тень учится со всех касаний (`desk/loop.py` 1281–1283).
  - Бумага чемпиона: `source=shadow` только при `shadow_would` (ACCORD ∧ TVH ∧ нет B-гейта).
  - Бумага претендента: `source=challenger`, если TVH есть, ACCORD нет, жюри не VETO, B не режет (`desk/loop.py` 1892–1901). Это и есть «жюри молчит — какой был бы R».
  - Fade spring — отдельный `source=fade`.
  - `DecisionTrace` кладёт A/B/C + intel-атом в ту же строку (`ops/decision_trace.py`).
  - Экзамен читает **закрытые** paper R (`champion/exam.py`); `promote` без ack не переворачивает стол.
  - Заготовка 2.9.5 `champion/veto_shadow.py` — статический отчёт veto on/off, ордеров нет, `promote()` без ack падает. В ночной проход не подключена как отдельный поток; живой учёт — `journal_touches`.

  `ShadowWriter` (`exec/shadow.py`) — тонкая запись `{mode, sent: False, payload}`; persistence — SQLite `put_journal_touch` на том же такте жюри. Второй таблицы и «асинхронной» очереди поверх этого нет смысла: нагрузка на ядро уже одна запись на касание. Дубль увеличит I/O и разъедет калибровку.

  Отличие от формулировки ARTEMIS: тень **уважает** B (`shadow_would = False` при `b_gate`, строки 1626–1630). Это закон («B — часть стратегии»), не дыра. Отдельный paper «B выключен» — это как раз заготовка `VetoShadow`, и она сознательно не шлёт ордера и не промоутит.

- **Менять нечего.** Калибровки по причине отказа считаются запросом к `journal_touches` (`skip_reason` ∈ {`b_veto`, `b_hold`, `SILENCE`, `VETO`, `NO_TVH`, …}), без новой схемы.

---

### Пункт 3. Префильтр новостного B

- **Статус:** Не требуется
- **Обоснование:**

  Предложение исходит из ложной посылки, что карточка B на каждый заголовок зовёт дорогой LLM.

  Горячий путь карточки — **детерминированный** `card/build.py:from_news`. LLM туда не импортирован.

  Префильтр «значимости» уже стоит числами, не моделью:

```17:17:src/capitalizator/card/build.py
IMMINENT_HOURS = 2
```

```54:59:src/capitalizator/card/build.py
    imminent = [
        row
        for row in calendar
        if row.event_class in {"CPI", "FOMC"}
        and timedelta_hours(row.event_time, when) <= IMMINENT_HOURS
        and row.event_time >= when
    ]
```

  - ≤2 ч до CPI/FOMC → `bearing_verdict=veto` (`fomc_inside_2h`). Тесты: `tests/card/test_intel_card.py::test_intel_cpi_inside_2h_vetoes`, `tests/card/test_ab_packages.py::test_p1_fomc_in_two_hours_is_veto`.
  - ≤24 ч → `cut_size`, `macro=0.5` (`pre_event_24h`). Тест: `test_intel_fomc_tomorrow_cuts_size`.
  - HACK/SEC с негативным токеном → veto сразу (`_negative`, не LLM).
  - Классификация заголовка — `news_macro/rss.py:classify_title` (строки).
  - Официальный календарь: `known_at ≤ now` обязательно (`hits = [row for row in calendar if row.known_at <= when]`).
  - `MacroRules` (24 ч pre + окна CPI/NFP/PCE/FOMC из `infra/time.yaml`) по умолчанию `enabled=False` — второй контур, не LLM.

  LLM живёт **только** в процессе `intel` как экстрактор утверждений (`intel/llm.py`, `intel/run.py:extract_claims`): до 60 текстов за 6 ч, бюджет `llm.monthly_budget_usd`, fallback = «не распарсено, не вызов». Ключей биржи нет (`Settings(..., exclude_prefixes=("bybit.",))`). Карточка читает уже лежащие `intel_item` + CSV-календарь. Закон 7 в `ARCHITECTURE-AZ.md` и `PRODUCT.md`: модель не советует и не обходит стоп.

  Префильтр «если до события >2 ч — не звать LLM» на этом пути не к чему прикрутить: LLM и так не вызывается от события календаря. Резать extract_claims по «нет HACK/CPI в title» — экономия копеек на стороне intel, не решение стола.

- **Менять нечего.** Внешний LLM для этого пункта не нужен.

---

### Пункт 4. EWMA-детекция пампа как B-veto

- **Статус:** Не требуется
- **Обоснование:**

  Модуля «памп цены/объёма на альтах» нет — и это не дыра ядра.

  Что уже закрывает тот же класс риска без нового часов:

  | Механизм | Где | Что режет |
  |---|---|---|
  | ОКО CASCADE / SPOOF / LAYERING / thin | `oko/shadow.py`, `oko/eyelid.py` | манипуляция книги; VETO — шестой голос жюри |
  | `weather.regime == VOL_EXPANSION` против bounce | `oko/eyelid.py` 129–131 | импульс vs отскок |
  | fragility: OI peak × funding top-5% × thin | `eyelid.py` 107–109, `desk/loop.py` `_fragility` | crowded long |
  | BTC-veto альта | `btc/veto.py` | лонг альта после слома поддержки BTC |
  | `rvol` на карточке | `card/volume.py`, `card/build.py` 121–135 | **плюс**, не veto (и при rvol>2, и при норме — `propose`) |
  | `authors/pump.py` | allow-list авторов | hold при sole whale; это не EWMA цены |

  `prs/score.py` `x_ewma` — EWMA **давления книги** в контуре A. Тащить его в B-veto пампа = вторжение в позвоночник. Рабочего ТФ 1m в столе нет (15m / 1h / 4h / 1d). Порог из arXiv:2503.08692 не калиброван на Bybit linear.

  Философия: честный быстрый ход альта на зоне + книге + CAV + ACCORD — это как раз вход A. Резать его «цена ушла от EWMA за 1 минуту → veto 15 минут» конкурирует с жюри и бьёт частоту на DOGE/SUI в импульсе. Грязный памп (спуф, каскад, тонкая книга) уже режет ОКО. Паспорт ОКО расширять ценовым EWMA **нельзя** (закон).

  Если когда-нибудь понадобится флаг для Granger/ночного отчёта — только journal-атом на альтах (`symbol_group != majors`), без `bearing_verdict=veto`, без живого блока, до экзамена C. Это не текущая работа.

- **Менять нечего.**

---

### Пункт 5. Журнал серии промахов B

- **Статус:** Не требуется
- **Обоснование:**

  Журнал решений B уже есть: `bearing_verdict`, `b_gate`, `DecisionTrace.contour_b`, intel-атом (`desk/loop.py` 1844–1862). Счётчика `b_consecutive_veto` нет.

  Предложенное правило «три veto за час → hold на час» **противоречит смыслу B и уроку Fin-Analyst**.

  - Veto B — факт календаря/HACK, не «промах». Три veto за час до CPI — правильное поведение; надстройка hold только удлиняет блок.
  - Fin-Analyst §6.1 (группа 2): система **без памяти повторяла неверный short**. Лечение — видеть расхождение решения с исходом, не стопорить вход после правильных veto.
  - Исходная рекомендация в `INDUSTRIAL-RE-2026.md` была другой: «если veto/hold N дней расходится с закрытым paper R — **флаг** в карточке, без автоослабления A». Это ночной отчёт C, не живой hold.
  - Автоhold по серии veto меняет частоту A, не трогая формально жюри, но подменяя его гейтом. Канон: B режет по факту, не по собственной инерции.

  Сброс «после успешной сделки» тоже ложен: успешная сделка не отменяет FOMC через 40 минут.

- **Менять нечего.** Если понадобится память Fin-Analyst — ночной diff `b_gate` vs закрытый `source=shadow` R в `ops/night.py` / Chronos, флаг без `hold`. Не сейчас: журнал уже позволяет этот запрос.

---

### Пункт 6. PIT-тесты на intel

- **Статус:** Уже реализовано
- **Обоснование:**

  Look-ahead = использовать строку **до** `known_at` (когда стол узнал). Использовать CPI **до** `event_time` — закон pre-event (veto/cut), не look-ahead.

  Закон в коде:

  - `from_news`: в карточку идут только `row.known_at <= when` (`card/build.py` 48–53).
  - `MacroRules._known` / `_event_window` — то же (`news_macro/rules.py` 62–73).
  - `us_data_known_at` / `cpi_day` — `known_at > when` пропускают (`risk/session.py` 67–81).
  - Intel: `known_at` = момент, когда **мы** увидели (`intel/fetchers.py` 1, 89). `published_at` лежит отдельно в payload и **не** подменяет `known_at` в `row_from_item` (`news_macro/from_intel.py` 30–35).
  - Срез хранилища: `NewsStore.query(..., as_of=)` / `tests/storage/test_pit_query.py`.

  Тесты, которые уже бьют look-ahead:

  | Тест | Что запрещает |
  |---|---|
  | `tests/news/test_pit.py::test_slice_before_known_at_is_empty` | срез до `known_at` пуст |
  | `tests/news/test_event_windows.py::test_unknown_row_is_not_a_window` | `known_at` в будущем → окна нет |
  | `tests/desk/test_loop.py::test_loaded_calendar_is_not_news_on_a_quiet_day` | CPI следующего месяца не новость бара |
  | `tests/test_pit.py`, `tests/authors/test_ingest.py`, `tests/whales/test_pit.py`, `tests/screener/test_unlock.py` | тот же штамп на смежных шинах |

  Прямого unit-теста «`from_news` + HACK с `known_at > now` не veto» нет — фильтр есть, покрытие семьи тестов достаточно. Добавлять ради строки не требуется.

  Оговорка (не дыра прод-пути): `Knowledge.intel_items` кладёт колонку `known_at`, затем распаковывает payload поверх (`ops/knowledge.py` 1087–1094). Если в payload вручную положить чужой `known_at`, он перебьёт колонку. Fetchers этого поля в payload не пишут. Имеет смысл помнить при ручном backfill.

- **Менять нечего.** Опциональный тест (не блокер):

```python
# tests/card/test_intel_card.py
def test_from_news_ignores_row_not_yet_known() -> None:
    future = row_from_item({
        "id": "rss-hack-future",
        "kind": "rss",
        "known_at": (NOW + timedelta(hours=1)).isoformat(),
        "text": "Protocol hack",
        "event_class": "HACK",
    })
    card = from_news(symbol="BTCUSDT", now=NOW, calendar=(future,), volume=VolumeSnapshot(rvol="3"))
    assert card.bearing_verdict != "veto"
    assert "coin_negative" not in card.minuses
```

  Плюс тот же кейс через `put_intel_item` + `publish_card`. Затронет только `tests/card/test_intel_card.py`. Прод-код не менять.

---

## Сводная таблица решений

| Пункт | Статус | Приоритет | Сложность (дни) |
|---|---|---|---|
| 1. SL-ack → flatten | Требуется, но с оговорками | высокий на demo/live | 1–2 |
| 2. Тень отвергнутых | Уже реализовано | — | 0 |
| 3. Префильтр новостного B | Не требуется | — | 0 |
| 4. EWMA-памп как B-veto | Не требуется | — | 0 |
| 5. Серия veto B → hold | Не требуется | — | 0 |
| 6. PIT-тесты intel | Уже реализовано | — | 0 |

---

## Итоговое заключение

- **Нужно и не ломает канон:** только пункт 1 — и не как Quant Flow в signer, а как решение стола: `amend_stop` с двойника, затем OMS `flatten` после грации ≥ 60 с. Детекция, липкий блок входов, баннер и алерт уже стоят.
- **Отложить / не делать:** пункты 2–5 в предложенной форме. Журнал отвергнутых, 2-часовой veto, учёт B и PIT-закон уже в коде. EWMA-памп и «3 veto → hold» либо дублируют ОКО/календарь, либо вредят частоте A.
- **Внешний LLM не нужен.** Существующий `intel.LLMClient` остаётся экстрактором в отдельном процессе (схема JSON, бюджет, без ключа биржи). Карточка B его не зовёт. Новый API, частота и «новостной префильтр» не требуются.
- Гипотеза «менять в коде нечего» **опровергается только пунктом 1**. Пять остальных предложений либо уже выполнены замыслом, либо противоречат ему.

  Нельзя сказать: «По итогам аудита изменений в код не требуется. Все предложенные улучшения либо уже присутствуют, либо избыточны/противоречат архитектуре.»

  Верно так: **пять пунктов закрыты или отклонены; один (SL не подтверждён → retry стопа, затем flatten через OMS стола) остаётся реальной дырой gateway/desk и не трогает ядро A.**

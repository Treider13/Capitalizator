# Финальный план A + B (утверждённая схема заказчика)

**Дата:** 2026-09-01  
**Статус:** схема принята. Пакеты P0–P8 реализованы.  
**Спотовый рельс:** вариант 2 (предложение + адаптер спота только после ручного ack на тикер вне 24).

Жёсткая привязка к живым функциям: `hours24`, `enable`, `status`, `observe`, `observe_if_on` в `src/capitalizator/ops/contour.py`; роли 1–3 и жюри — `zones`, `tape`, `prs`, `zlg`, `patterns/cav`, `jury/desk`, `btc`; вход — `exec/strategy_bounce.propose`; риск — `risk`; ключ — только `signer`.

---

## 0. Два контура

| Контур | Скорость | Задача | Решение | Ордер |
|---|---|---|---|---|
| **B аналитик** | 5–60 с | Сессии, POC/VAH/VAL, Fib, новости, авторы, GEX, ICT/SMC как **метки**, TradingAgents, макро | `veto` / `cut_size` / `propose` / `hold` + `macro_multiplier` + B-метки | **не шлёт** |
| **A исполнитель** | тик / закрытая свеча | recorder → book → зоны/лента/PRS/ZLG/CAV/жюри/BTC → proposer → risk → exec+signer | `ACCORD` / `SPLIT` / `VETO` | **шлёт только signer** |

LLM в A не ходит. Ключ видит только `signer`.

**Стык.** B пишет в knowledge/SQLite на пару: `bearing_verdict`, `macro_multiplier`, B-метки (`fib_zone`, `rsi_htf`, `gex_bg`, `fvg_status`, `sweep_status`, `market_regime`, `jury_b`). A **обязан** исполнить `veto` (skip/flatten, не спорит) и умножить qty на макро. Быстрый пропуск входа A делает сам: зона × 8 с книги × CAV × BTC × Accord-or-Silence.

B **не считает** ZLG, CAV, tape eaten, PRS. Это только A. Объёмы в B — сессионный профиль (POC/VAH/VAL) и контекст, не жест книги.

---

## 1. Привязка функций A к файлам (уже есть)

| Имя в плане | Файл | Что делает сейчас | Что дописать |
|---|---|---|---|
| `hours24` | `ops/contour.py` | лента 24ч, `max-unmarked-gap-s 0` | без зелёного A не `enable` — уже закон |
| `enable` | тот же | человек, отказ если hours24 красный; `phase.yaml` не пишет; `trading_mode` не меняет | не трогать закон |
| `status` / `contour_state` | тот же | on/off, `can_enable`, без советов | ок |
| `observe` | тот же | **одно касание**: tape → ZLG → CAV → BTC → `stamp_jury`. **Размер не открывает** | до `propose` не ходит; стык B читать **до** ролей, если B-метки красные |
| `observe_if_on` | тот же | читает кнопку из SQLite, булевым не обойти | ок |
| `recorder` | `recorder/` | trades, L2, BBO, funding, OI, gap+resync | живой сокет — шаг VPS |
| `book` | `book/reconstruct.py` | best, spread, depth, imbalance | ок |
| `zones` роль 1 | `zones/` | прошлое: cluster, round, prior H/L, swing; `vp_hyp` POC | VAH/VAL как границы range из B-метки `market_regime=range` |
| `tape` роль 2 | `tape/classify.py` | eaten ≥50% depth_near за 8 с; OFI | снять хардкод `wall_no_print=False` |
| `PRS` | `prs/score.py` | τ возврата глубины, Y; журнал / `prs_cut` | считать в цикле касания |
| `ZLG` | `zlg/gesture.py` | DEFEND/RETREAT/IMPROVE/FADE/SILENCE, A_* | ок |
| `CAV` | `patterns/cav.py` | REJECT/THROUGH/COMPRESS/DRIFT/NOISE | ок |
| `жюри` | `jury/desk.py` | CAV × ZLG × tape × BTC × **card** | card = голос B; плюс предфильтр B-меток |
| `btc` роль 3 | `btc/` | trend/box/news; вето слома | ок |
| `screener` | `screener/filters.py` | вселенная, спред, анлок | не «киты в стакане» |
| `proposer` | `exec/strategy_bounce.py` `propose` | ACCORD + гейты → Intent | читать B veto/макро/метки **первым** |
| `risk` роль 5 | `risk/` | accept/cut_size/reject; нет доливки | `qty *= macro_multiplier` |
| `exec+signer` | `exec/`, `signer/` | очередь SQLite; send сейчас заглушка | спот-рельс — отдельный пакет после ack |

Жюри в коде уже пятиголовое: пятый голос — карточка. В этой схеме карточка = выход B. `n<20` на CAV/ZLG даёт голос `0`, не «всё жюри SILENCE». SILENCE — когда CAV и ZLG оба 0. Так и оставляем (закон файла, не таблицы «n<20 = SILENCE»).

`observe()` **не шлёт ордер**. Цепочка после жюри: `DeskLoop` / `propose` → `risk` → `intent_queue` → `signer`. Так и собираем, не запихиваем ключ в `observe`.

---

## 2. Контур B — что передаёт в A

На каждую пару из 24 (и отдельно `spot_proposal` вне 24):

```
CardLive {
  bearing_verdict: veto | cut_size | propose | hold,
  macro_multiplier: 1.0 | 0.5 | 0.3,
  fib_zone,          # OTE | 0.5-1 | forbidden_0_0.5 | none
  rsi_htf,
  gex_bg,            # строка или none; фида Deribit пока нет
  fvg_status,        # метка журнала, не ICT-движок истины
  sweep_status,      # done | pending | none
  market_regime,     # trend | range
  poc, vah, val,     # прошлый сессионный профиль
  htf_bias,
  jury_b,            # голоса TradingAgents, если карантин позволил
  pluses[], minuses[],
  known_at
}
```

B пишет это в `knowledge` (SQLite), не в signer.

### Источники B (закон файла, не «все соцсети»)

В `authors/sources.py` и `PRODUCT.md` **запрещены** `telegram`, `scrape`, `tip`.  
При «Приступай» B-насос = `rss` / `reddit_json` / `tradingview_own` + официальные календарные фиды (Fed, BLS, анонсы биржи) + то, что уже в `macro.csv`.  
Twitter/TG **не подключаю**, пока заказчик явно не снимет запрет в `PRODUCT.md`. Иначе это другой продукт, не «по вашему файлу».

GEX: колонка `gex_bg` уже в журнале, фида нет. Считаем метку, когда появится официальный доступ; пустое = `none`, не выдумка.

ICT/FVG/sweep в B — **метки карточки**, не движок входа. Lookahead SMC-либ в A не тащим.

TradingAgents — только B, ≥60 с, карантин без ключей (`llm/sandbox.py` режет egress). Независимый прогон в доке −25.4%: голос `jury_b` — метка, не ордер.

---

## 3. Стык (как собираем после «Приступай»)

1. B каждые N секунд пишет `CardLive` в SQLite на символ.
2. `observe_if_on` / `propose` читает карточку **сначала**:
   - `veto` → skip; открытая позиция → `TradeManager.on_refute` → flatten. Роли 1–3 можно не гонять для входа.
   - `hold` → ничего.
   - красные B-метки (Fib в 0–0.5, sweep pending, `jury_b` «за» < 3 из 7) → `SPLIT`, ZLG/CAV для **входа** не запускаем (журнал тени всё равно можно посчитать отдельно, чтобы таблица росла).
   - `propose` / `cut_size` + зелёный контекст (≥4 из 5 меток) → полная цепочка A: tape, ZLG, CAV, BTC, жюри файла.
3. A `ACCORD` + B `propose` → risk, qty × 1.0.
4. A `ACCORD` + B `cut_size` → risk, qty × макро (0.5 / 0.3).
5. A `SPLIT` при любом `propose` → входа нет. Последнее слово A на **быстрый** пропуск.

Таблица решений заказчика (закон этой сборки):

| B-вердикт | B-метки | Роли A | Исход |
|---|---|---|---|
| `veto` | любые | любые | VETO skip/flatten |
| `hold` | любые | любые | HOLD |
| `propose` | ≥4/5 зелёных | ACCORD | вход, макро 1.0 |
| `propose` | ≥4/5 | SPLIT | ждём |
| `propose` | <4 зелёных | ACCORD | SPLIT (контекст) |
| `cut_size` | ≥4 | ACCORD | вход, макро 0.5/0.3 |
| `cut_size` | <4 | ACCORD | SPLIT |

---

## 4. Боковик

B: `market_regime=range` (своя метка; ADX в коде нет — не выдумываем ADX, режим из HTF/профиля B).  
A: цена у VAL → кандидат лонг отскок (tape не ест, ZLG DEFEND/IMPROVE). У VAH → шорт. Середина → SPLIT. Это уже закон mid + зоны; VAH/VAL подставляем из карточки B / `vp_hyp`, не из будущих баров.

---

## 5. Спот (вариант 2)

- Тикер в 24 перпах → обычный путь A после B.
- Новый токен: B пишет `spot_proposal` (потенциал, минусы, базовая ставка листингов). Ордера нет.
- Спот-адаптер + ручной ack на символ вне 24 — отдельный пакет после зелёных примеров 1/3/4 на перпах.

---

## 6. Пакеты после «Приступай» (без кода в промежуточных ответах)

Порядок: **П0 → П1 → П2 → П3 → П4 → П6**, затем П7 экран `[TOUCH]`, П5-B спот, П8 авторы.

| П | Содержание |
|---|---|
| П0 | Контракт `CardLive` в knowledge; `observe`/`propose` читают B первым |
| П1 | Календарь всегда в desk + внезапные официальные ленты; макро на qty; пример 1 flatten/skip |
| П2 | Карточка плюсы/минусы; несущий REFUTED → flatten; пример 3 |
| П3 | B-метки Fib/RSI/FVG/sweep/GEX/range как фильтр **перед** ролями входа; журнал колонок уже есть |
| П4 | Снять хардкоды: `wall_no_print`, `next_target`, `bearing` не None |
| П6 | Пример 4: propose + ACCORD + 1R/2 + trail за структурой |
| П7 | Консоль `[TOUCH]` = метки B + метки A |
| П5-B | Спот-рельс + ack |
| П8 | Allow-list авторы; TG нет |

Приёмка: примеры 1, 3, 4 автотестами на обоих контурах. Пример 2 — propose + `spot_proposal` до отдельного ack.

---

## 7. Подтверждение

- Вариант 2 (спот-рельс) — да.
- Контур A — строго функции файла, LLM нет.
- Контур B — сессии, профиль, Fib, GEX-слот, ICT/SMC как метки, TradingAgents в карантине.
- Стык: B → bearing/макро/метки → A роли 1–3 → risk → exec+signer.
- Источники: не Telegram, пока не снят запрет в `PRODUCT.md`.

**Реализацию не начинаю до слова «Приступай» в чате.**

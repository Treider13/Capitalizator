# Валидация релиза — 2026-09-01

Проверял `origin/main` @ `280e619` (merge PR #10). Последний функциональный коммит BTC bus: `c279970`.  
Не «кажется»: каждый пункт ниже — тест или прямой осмотр кода.

**Заключение: требуется доработка.** Бумажный организм (тень, жюри, SQLite-очередь, консоль) зелёный. Живой send на testnet/mainnet — заглушка. На VPS как «кнопка Демо шлёт ордер» ставить нельзя.

---

## Шаг 1. История коммитов и дыры §1 — ПРОЙДЕНО

### `c279970` закрывает BTC bus

Коммит: `audit: BTC bar close writes regime onto the alt bus (§6.7)`.

Осмотр `DeskLoop._publish_btc_bus` (`src/capitalizator/desk/loop.py`):

- После **любого** закрытия бара BTC (включая H4) вызывается `BtcRegime.classify` → `self.btc.regime`.
- Ручной прогон: три закрытых 4h бара 2026-08-30 → `desk.btc.regime == "trend"`.
- Тест `tests/desk/test_loop.py::test_btc_htf_close_writes_regime_bus` это же фиксирует.

`broke_support` / `broke_resistance` пишутся **не** на H4, а на `working_tf` (15m) + `tape_eaten`. Это закон `Break.detect` (`src/capitalizator/btc/break_def.py`: `if bar.tf != tf: return False`).  
Ручной прогон: H4 close за зоной + eaten → `broke_*` остаются False; 15m close `9.5` ниже support + eaten → `broke_support=True`.

Старая дыра «regime всегда None, альты не видят HTF» — закрыта. Писать `broke_*` на H4 было бы нарушением определения слома.

### Дыры из таблицы §1 — закрыты в волнах

| Дыра | Доказательство закрытия |
|---|---|
| `book_pre` на живом врёт | `on_trade` делает `st.book_pre = st.book.snapshot_copy()`. `fill_tape(book_pre=…)`. `test_14_eaten_uses_book_pre`, `test_book_pre_is_frozen_at_touch` |
| `stamp_jury` неполный | `Registry.stamp_jury` принимает wall / btc_break / card / cpi / trades_in_window / btc_same_side. `test_stamp_jury_honors_wall_and_btc_and_card` |
| `propose` не читает жюри | `BounceStrategy` при `require_jury` (desk ставит True) зовёт `voices_for_*` + `decide`; не-ACCORD → None. DeskLoop передаёт `jury=` в снимок |
| BTC-вето не в propose | `self.btc_veto.allow(...)` в `strategy_bounce.py`; `test_07_btc_break_vetoes_sol_long` |
| SILENCE = ACCORD | `test_silence_zlg_is_veto_not_accord` → VETO |

---

## Шаг 2. Приёмочные тесты §9 — ПРОЙДЕНО

Файл: `tests/product/test_acceptance.py`.  
Скипов нет. Собрано **28** тестов (25 нумерованных §9 + 3 доп. замка). Все зелёные.

```
python3 -m pytest tests/product/test_acceptance.py -o addopts= -v --tb=no
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.4.2, pluggy-1.6.0 -- /usr/bin/python3
collected 28 items

tests/product/test_acceptance.py::test_01_replay_is_deterministic PASSED
tests/product/test_acceptance.py::test_02_asia_journal_no_send PASSED
tests/product/test_acceptance.py::test_03_accord_off_does_not_send PASSED
tests/product/test_acceptance.py::test_04_demo_window_sends PASSED
tests/product/test_acceptance.py::test_05_demo_outside_window_no_send PASSED
tests/product/test_acceptance.py::test_06_reject_retreat_is_split PASSED
tests/product/test_acceptance.py::test_07_btc_break_vetoes_sol_long PASSED
tests/product/test_acceptance.py::test_08_average_in_schema_fails PASSED
tests/product/test_acceptance.py::test_09_twenty_by_four_by_five_rejects PASSED
tests/product/test_acceptance.py::test_10_refuted_card_no_send PASSED
tests/product/test_acceptance.py::test_11_llm_poison_is_not_advice PASSED
tests/product/test_acceptance.py::test_12_dead_man_cancel_all PASSED
tests/product/test_acceptance.py::test_13_future_zone_is_invisible PASSED
tests/product/test_acceptance.py::test_14_eaten_uses_book_pre PASSED
tests/product/test_acceptance.py::test_15_mid_equals_print_is_silence PASSED
tests/product/test_acceptance.py::test_16_twenty_four_ok_twenty_five_rejected PASSED
tests/product/test_acceptance.py::test_17_post_order_is_405 PASSED
tests/product/test_acceptance.py::test_18_post_mode_without_ack_is_403 PASSED
tests/product/test_acceptance.py::test_19_episode_live_is_accepted PASSED
tests/product/test_acceptance.py::test_20_hello_banner_when_missing PASSED
tests/product/test_acceptance.py::test_21_parquet_lock_is_regular PASSED
tests/product/test_acceptance.py::test_22_symlink_vault_refused PASSED
tests/product/test_acceptance.py::test_23_first_minute_blocks_breakout PASSED
tests/product/test_acceptance.py::test_24_failed_break_gets_new_card_id PASSED
tests/product/test_acceptance.py::test_25_n_zlg_19_no_send PASSED
tests/product/test_acceptance.py::test_26_us_cpi_noon_journals_but_does_not_send PASSED
tests/product/test_acceptance.py::test_demo_adapter_default_is_not_sent PASSED
tests/product/test_acceptance.py::test_set_mode_with_ack_does_not_write_phase PASSED

============================== 28 passed in 0.61s ==============================
```

Дополнительно: `tests/audit/test_plan.py` + `tests/ops/test_product.py` + связанные desk/macro/btc/signer — все зелёные в том же прогоне (105/105, 0 skip).

---

## Шаг 3. Критические сценарии — НЕ ПРОЙДЕНО

| Сценарий | Итог | Доказательство |
|---|---|---|
| Testnet hello: лимит далеко от mid + cancel | **НЕ ПРОЙДЕНО** | `signer/__main__.py`: `send=lambda row: {"status": "not_sent"}`. HTTP к Bybit нет. `mark_hello` — флаг в SQLite. Баннер «Демо: нет hello» работает (`/api/status`). |
| off/learn: тень есть, ордера нет | **ПРОЙДЕНО** | `test_03`, desk `desk_mode=off` если не demo/live. `pending_intents()` пуст. |
| demo + ACCORD + окно 16:30–19:30 МСК → testnet | **НЕ ПРОЙДЕНО** | Очередь SQLite заполняется (`test_demo_hello_sends_stop_in_payload`). Signer не шлёт на биржу. |
| live → сабаккаунт mainnet | **НЕ ПРОЙДЕНО** | `Signer.validate`: `trading_mode` только `testnet`. Mainnet — отказ. Send всё равно заглушка. |
| 03:00 МСК: строка touch, sent=false | **ПРОЙДЕНО** | `test_02_asia_journal_no_send` (`ASIA` = 00:00Z = 03:00 МСК) |
| Макро CPI: ×0.5 и запрет 14–15 ET | **НЕ ПРОЙДЕНО** | `MacroRules` считает верно (`test_macro_rules`: ×0.5, `et_blackout`). `propose()` проверяет только `macro.allow`. `size_mult` на `Intent` не копируется. Риск не режется. |
| First-fact n_zlg=19 | **ПРОЙДЕНО** | `test_25_n_zlg_19_no_send`; `resolve()` → `shadow_gesture`, `size_mult=1` |
| SILENCE при mid == trade_px | **ПРОЙДЕНО** | `test_15_mid_equals_print_is_silence`; жюри SILENCE → VETO |
| BTC-вето лонг альта | **ПРОЙДЕНО** | `test_07` + мок `BtcVeto().allow(...)` |
| Dead-man: убить signer → cancel_all через 30 с | **НЕ ПРОЙДЕНО** | Юнит `DeadMan.tick` зелёный. `DeadMan` живёт **внутри** signer. `SIGKILL` не вызывает `finally`/`on_signer_exit`. `cancel_all` — локальный `list.append`, не биржа. Внешнего супервизора нет. |

### Минимальные исправления (шаг 3)

1. **Hello / demo send.** В signer инжектировать реальный `post` (testnet REST): лимит далеко от mid + сразу cancel; при 2xx — `mark_hello(ok=True)`. Без ключа процесс стартует, send закрыт, баннер остаётся.
2. **Live.** Расширить `UnsignedIntent.trading_mode` до `testnet \| mainnet` только при `user_mode=live` + отдельный vault-ключ сабаккаунта. Host не хардкодить.
3. **Макро ×0.5.** В `BounceStrategy.propose` после `macro.decide`: `intent.size_mult = macro.size_mult` (или `qty *= size_mult`). Тест: pre-CPI в окне → qty вдвое меньше базового.
4. **Dead-man.** Внешний watchdog (systemd `WatchdogSec=30` или отдельный процесс), который шлёт `cancel_all` если signer не бьёт heartbeat в SQLite. `on_signer_exit` должен звать тот же injected exchange cancel, не `list.append`.

---

## Шаг 4. Запрещённый функционал §12 — ПРОЙДЕНО

Обход `src/` (не docs/):

| Запрет | В коде |
|---|---|
| Nautilus | Только комментарий «Nautilus is not pulled in» в `exec/replay.py`. Импорта нет |
| ClickHouse | Нет |
| shadow opponent | Нет движка; `promote()` бросает «no auto promote» |
| публичный дашборд | Консоль только `127.0.0.1` |
| LOBSTER | Нет |
| фандинг-керри | Нет стратегии; funding — журнал/стрим |
| Deribit GEX | Поле `gex_bg` в журнале, фида нет, входа нет |
| авто-promote | Явный отказ |
| риск 2% | `F1_TARGET=0.01`, `F5_TARGET=0.012`. Консоль: `target_risk: 0.01` |
| ордера вне окна | `in_desk_window` 16:30–19:30 МСК; `test_02`/`test_05` |
| скрейп TV/TG | `FORBIDDEN_KINDS` включает telegram/scrape; ingest бросает |
| копия кита | `whales/` не принимает вход |
| ICT-движок | Комментарии «No ICT/FVG»; методов нет. Поле `fvg_present` в журнале — колонка, не движок |

Константы: `MAX_SYMBOLS = 10`. `infra/universe.yaml` — топ-10 линейных USDT-перпов. 11-й — отказ (`test_16`).

`infra/registry.yaml`: есть `htf_d1`, `mid_band_ticks`. Лишний ключ — `RegistryConfigError` (`test_extra_key_rejected`).

---

## Шаг 5. Готовность к установке §11 — НЕ ПРОЙДЕНО

| Пункт чеклиста | Итог |
|---|---|
| recorder / desk / signer / console — отдельные процессы, SQLite | **ПРОЙДЕНО.** `python -m capitalizator.{recorder,desk,signer}` и `ops.console`. Desk пишет `intent_queue`, signer читает. `has_key: false` у desk |
| Инструкция Vault и ключей | **ПРОЙДЕНО как документ.** `docs/VPS.md`, `docs/VAULT-LAPTOP.md`, `ops/key-checklist.md`. `init_vault` пишет `secrets/README.md` («ключи не класть»). `.env.example` без значений |
| healthz рекордера :8081 | **ПРОЙДЕНО.** Поднял `--serve --port 18081` → `GET /healthz` = `200 ok`. Дефолт порта в CLI = 8081 |
| консоль 127.0.0.1:8082 статус | **ПРОЙДЕНО.** `--serve --port 18082` → `/healthz` 200, `/api/status` JSON, баннер «Демо: нет hello». `0.0.0.0` — отказ |
| withdraw off при старте | **НЕ ПРОЙДЕНО.** Нет проверки в `signer/__main__`. Есть только чеклист (галочки пустые) и `gate_f0` читает `[x]` из markdown |

Живой hello на тестнете без ключа в этом окружении запустить нельзя — кода отправки нет, не только ключа.

---

## Сводка шагов 1–5

| # | Что | Вердикт |
|---|---|---|
| 1 | История + BTC bus + дыры §1 | **ПРОЙДЕНО** |
| 2 | 25 приёмочных тестов §9 | **ПРОЙДЕНО** (28/28, 0 skip) |
| 3 | Критические сценарии | **НЕ ПРОЙДЕНО** |
| 4 | Запреты §12 + registry/universe | **ПРОЙДЕНО** |
| 5 | Чеклист установки §11 | **НЕ ПРОЙДЕНО** |

---

## Заключение

**Требуется доработка.** Не деплоить на VPS как торгового бота.

Можно ставить только контур записи + тень (recorder + desk + console, `user_mode=off|learn`): лента, журнал, жюри, баннер hello. Кнопку Демо/Live не нажимать — очередь не уйдёт на биржу, hello — флаг в SQLite, dead-man не снимет чужие ордера после `kill`.

После минимальных пунктов шага 3 + проверка withdraw при старте signer — повторить этот отчёт.

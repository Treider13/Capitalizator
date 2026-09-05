# Промышленный реверс-инжиниринг AI-систем для криптофьючерсов (2024–2026)

**Дата сбора:** 2026-09-04.  
**Метод:** сверка именованных объектов со статьями, DOI, релизами GitHub и исходным кодом.  
**Правило:** если объекта нет в открытом поле — «не обнаружено». Декларация статьи и реализация в коде разделены.

## Реестр верификации (что из списка существует)

| Заявленное имя | Статус | Источник |
|---|---|---|
| LLM-Trader (IEEE 2026, мультимодальный, событийный) | **не обнаружено** как статья/система с этим титулом | Поиск arXiv/IEEE/GitHub по точному титулу пуст. Ближайшие: Janus-Q arXiv:2602.19919; F2Agent arXiv:2608.05668; MM-DREX arXiv:2509.05080 |
| CryptoNewsTrade | найдено | KSEM 2026, LNCS 16634, с. 481–493, DOI 10.1007/978-981-92-2859-1_35 (Zhang, Chen, Cai, Liu, Cai) |
| Fin-Analyst / FinMMEval 2026 | найдено | arXiv:2607.12233; CLEF 2026 FinMMEval Lab |
| CryptoTrade | найдено | EMNLP 2024, ACL anthology 2024.emnlp-main.63; код `Xtra-Computing/CryptoTrade` |
| Meta-RL-Crypto | найдено | arXiv:2509.09751 |
| ARTEMIS (shadow mode) | найдено | Zenodo 10.5281/zenodo.18841943, v1.1 |
| TraderBench | найдено | arXiv:2603.00285; OpenReview ICLR 2026 AIWILD |
| Pump-and-Dump (Hawkes / EWMA / signatures F1 88%) | найдено **как три отдельные линии работ**, не как одна система 2024–2026 | signatures: arXiv:2201.02441 (F1 до 88%); EWMA: arXiv:2503.08692; Hawkes: Eur. J. Finance 2026 DOI 10.1080/1351847x.2026.2624485 |
| TradingAgents v0.3.1 | найдено | `TauricResearch/TradingAgents` tag v0.3.1 (2026-07-05) |
| FFRDM (Bybit, 7 сигналов, −80–90% LLM, VETO, рефлексия) | **не обнаружено** | Нет репозитория/статьи с этим именем. Ближайший открытый аналог по признакам: `poliakarmai/bybit-ws` (7 фильтров входа + Entry Judge + Risk Manager) |
| Quant Flow | найдено | `web3spreads/quant-flow` |
| Onchain-AI-Hedge-Fund | найдено | `LoopGlitch26/Onchain-AI-Hedge-Fund` |
| Quant 2.0 (229 рынков, ретрейн 15 мин, 5× вес убытков) | **не обнаружено** | Нет репозитория/статьи с этой тройкой признаков |
| MAHORAGA | найдено | `ygwyg/MAHORAGA` |
| Alpha Arena 2025 | найдено | nof1; итоги в SCMP, GuruFocus, RootData, ForkLog (цитата Jay A. Zhang) |
| AriseAlpha | найдено как пресс-релиз | GlobeNewswire 2026-05-19; независимый код/аудит не обнаружен |
| Fere AI ($1.3M) | найдено | GlobeNewswire 2026-04-23; docs.fereai.xyz |
| OneBullEx / OneALPHA / 300 SPARTANS | найдено как PR | PR Newswire 302727385; код и аудит PnL не обнаружены |

---

# Часть 1. Досье

## 1. CryptoNewsTrade (KSEM 2026)

### A. Архитектура (статья; кода нет)

1. **Данные.** Неструктурированные новости в реальном времени; минутый цикл; акцент на альткоинах, не только BTC/ETH. Источник: Springer Professional abstract (Zhang et al., KSEM 2026). Предобработка и признаки в открытом коде: **не обнаружено**.
2. **Решения.** LLM извлекает знание из новостей и выдаёт сигналы поддержки решений. Парадигма «реакция на событие», не прогноз цены (тот же abstract). Промпты: **не обнаружено**.
3. **Риск.** В abstract заявлено превосходство в risk control vs MACD/BB/LSTM/Transformer/CryptoTrade. Числовые лимиты, VETO, стоп: **не обнаружено**.
4. **Обучение.** «Feedback-driven knowledge refinement» — итеративная правка логики по обратной связи (abstract). Теневой режим / частота ретрейна: **не обнаружено**.
5. **Исполнение.** Live-эксперимент заявлен на май 2025. Кто держит ключи, что при сбое: **не обнаружено**.

**Статья vs код:** статья есть (paywall LNCS). Публичный код: **не обнаружено**. Цифры 80.46% / Sharpe 7.83 — только из abstract, без протокола издержек, проскальзывания, walk-forward и без независимого аудита.

### B. Провалы

Сравнение с CryptoTrade в abstract: авторы ставят CryptoTrade как baseline и заявляют превосходство, особенно на DOGE. Воспроизвести нельзя: нет кода.

### C. Скрытые приёмы

Недоступны: репозитория нет.

**Оценки:** данные 6 (новости + минута, без стакана/ончейна в тексте) · решение 5 (декларация LLM) · риск 2 (нет кода) · адаптация 4 (задержка refinement) · исполнение 1 · проверяемость 2 · реальные результаты 3 (live май 2025 без аудита).

---

## 2. Fin-Analyst (FinMMEval 2026 Task 3)

Источник: arXiv:2607.12233 (Rashid, Hong, Ding, Hossain), leaderboard 2026-07-05.

### A

1. **Данные TSLA:** 7 корпусов в память при старте: news bundle организатора, 8-K, 10-Q, 10-K, Compustat, IBES, техника (MACD/RSI/BB/ADX), r/wallstreetbets. **Данные BTC:** цена организатора, momentum label, Fear & Greed (alternative.me). Частота: дневной online protocol. Стакан / ончейн / 8с книга: **не обнаружено**.
2. **Решения.** TSLA: 8× `gpt-4o-mini` (temp 0.1, JSON `{action, confidence, reasoning}`) + Meta-Agent. Веса Meta (Table 8): NEWS (override при conf>0.70) ≻ Event ≻ Earnings ≻ Technical ≈ Fundamentals ≈ Analyst ≻ Social ≻ Strategy; ≥5 согласных — следовать. **BTC: LLM-пайплайн не вызывается.** Три правила: тренд ±0.5% по окну истории, F&G ≥60 BUY / ≤40 SELL, momentum bullish/bearish; ничья — F&G ≥50 BUY else SELL (§3.4).
3. **Риск.** Действие ∈ {BUY, HOLD, SELL}. Исключение специалиста → HOLD (§3.5). Размер/стоп/плечо: **не обнаружено** (арена задаёт исполнение). Риск в промпте Meta, не в коде лимитов.
4. **Обучение.** Stateless prompt, «store nothing across time» (§6). Кэш MD5 одинаковых промптов. Рефлексии нет.
5. **Исполнение.** FastAPI на Hugging Face Spaces. Ключей биржи нет. Сбой агента → HOLD.

### B (ответы на вопросы шаблона)

- **Короткое окно переворачивает рейтинг.** Interim 2026-06-04: TSLA +2.0%, BTC +6.4%. Финал: TSLA +13.51% (1st), BTC −5.30% (13th). Figure 2, §5.2.
- **AI без памяти повторяет ошибку.** TSLA short 6 дней подряд на росте +6% (05-21…05-28), MDD −6.1%. BTC short последние 2 дня на росте, −1.8%. Причина в тексте авторов: нет памяти, система не видит серию промахов (§6.1, группа 2).
- **Новости как шум.** Ablation Table 6: отключение 10-K даёт Δ-CR **+2.42 pp**, Compustat **+2.95 pp** — годовые каналы ухудшают дневной горизонт. News критичен (−11.74 pp при отключении), но §6: «slow moving inputs … diluted that opportunity».

### C

Промпты Table 8 жёстко кодируют пороги (RSI>70 → SELL 0.65; WSB не контрариан). Это не «свободное рассуждение». BTC порог ±0.5% при типичном дневном ходе BTC 2–3% дал −8.1% на флэте 06-11…06-22 при движении рынка +1.3% (§6.1, группа 3).

**Оценки:** данные 7 (TSLA мультиисточник; BTC бедно) · решение 6 (TSLA) / 3 (BTC правила) · риск 3 · адаптация 2 · исполнение 4 (HOLD на сбое, нет ключей) · проверяемость 7 (промпты+логи арены) · результаты 6 (live арена, короткое окно).

---

## 3. CryptoTrade (EMNLP 2024)

Источники: ACL 2024.emnlp-main.63; arXiv:2407.09546; код `/tmp/audit-repos/CryptoTrade`.

### A — статья

1. **Данные.** On-chain: CoinMarketCap OHLC/volume/mcap; Dune — txn count, active wallets, value transferred, gas. Off-chain: GNews, фильтр Bloomberg/Yahoo/crypto.news. Дневной шаг. BTC/ETH/SOL. Стакан: **не обнаружено**.
2. **Решения.** Market analyst + news analyst (GPT-3.5-turbo саммари) + trading agent: доля ∈ [−1,1] или hold. Reflection agent смотрит неделю промптов/решений/доходностей (§2.4).
3. **Риск.** Комиссия пропорциональна обороту. Стоп/лимит плеча в статье: **не обнаружено**.
4. **Обучение.** Zero-shot, без fine-tune. Рефлексия — текстовый план в память.
5. **Исполнение.** Симулятор, старт $1,000,000, 50% кэш. Live-биржа: **не обнаружено**.

### A — код (`run_agent.py`, `eth_env.py`, `generate_reflections.py`)

- Флаги `--use_tech --use_txnstat --use_news --use_reflection`; `--price_window 7`, `--reflection_window 3`.
- `ETHTradingEnv`: SMA 5–30, MACD; комиссии `GAS_FEE` + `EX_RATE = 4e-3`.
- Рефлексия в коде **не совпадает** с формулировкой статьи: `generate_reflections.py` строки 9–20 — шаблон Reflexion «You were unsuccessful… Devise a concise, new plan», модель `gpt-3.5-turbo`. Срабатывает только если `not env['is_success']`. Статья говорит «анализирует неделю и находит самую влиятельную информацию».
- ACL abstract (опубликованный): превосходит **time-series baselines, but not … traditional trading signals**. arXiv v1 abstract писал «compared to traditional trading strategies» — расхождение версий.
- Таблица 2 BTC bull: Buy&Hold 39.66% vs Ours(GPT-4) 26.35% — B&H выше. ETH bull: Ours(GPT-4) 25.72% vs B&H 22.59%.

### B

Новости включены флагом; отдельного ablation «новости вредят» в прочитанных таблицах нет. Публичная версия ACL прямо снимает претензию «бьём классические сигналы».

### C

Рефлексия — verbal RL на неуспехе, не градиент. Ключей нет: это бенчмарк.

**Оценки:** данные 6 · решение 5 · риск 2 · адаптация 5 (рефлексия) · исполнение 2 · проверяемость 8 (код+таблицы) · результаты 4 (симулятор; на BTC bull слабее B&H).

---

## 4. Meta-RL-Crypto (arXiv:2509.09751)

### A — статья

1. **Данные.** CMC OHLC; Dune gas/wallets/tx; GNews + SimHash дедуп. Дневной прогноз. Стакан: **не обнаружено**.
2. **Решения.** Одна LLM (fine-tune Llama-7B) в ролях Actor / Judge / Meta-Judge. Actor: α_t ∈ [−1,1]. Judge: вектор наград return, Sharpe, drawdown, liquidity, sentiment cosine. Meta-Judge: DPO-style preference. GPRO (Tang et al. 2024).
3. **Риск.** Награда за drawdown и slippage; комиссия 10 bp; slippage N(0,0.05%) BTC/ETH, 0.12% SOL. Жёсткий VETO-код: **не обнаружено**.
4. **Обучение.** K кандидатов nucleus p=0.9 T=0.7; Elo судьи; кратчайший top-tier vs длинный low-tier (анти length-bias).
5. **Исполнение.** Симулятор $1M. Публичный прод-код: **не обнаружено**.

### C — цикл «Исполнитель → Критик → Метакритик» (как в статье, не в коде)

1. Actor семплирует K прогнозов.  
2. Judge ставит multi-objective вектор → MLP → скаляр.  
3. Meta-Judge учится предпочитать лучший скаляр (`L_meta = −log σ(M_φ(r1,r2))`).  
4. Judge дистиллируется в Meta-Judge (`L_align` MSE).  
5. Actor — preference loss к лучшему Elo-кандидату.

**Дефект статьи:** Table 1 помечает BTC 2025-04-08…05-23 (+35.56%) как «Test Bearish», а 2025-01-30…02-28 (−18.68%) как «Test Bullish». Подписи режимов противоречат знаку тренда. Table 2 (Bull 42% / Bear −8%) опирается на эти сплиты.

**Оценки:** данные 6 · решение 6 (заявлено) · риск 3 · адаптация 7 (петля) · исполнение 1 · проверяемость 3 (нет кода; битая Table 1) · результаты 3.

---

## 5. ARTEMIS (Zenodo v1.1, 2026-03-02)

Источник: DOI 10.5281/zenodo.18841943; kinqo.com.

### A

1. **Данные.** Live crypto; детали ленты в abstract не раскрыты. Стакан как отдельный слой: **не обнаружено**.
2. **Решения.** 5 агентов: historical analyzer, real-time scanner, dynamic executor, closure agent, Bayesian optimizer. AWS Lambda. Не LLM-жюри.
3. **Риск.** Shadow = симуляция **отклонённых** сигналов при 0 капитале; на закрытии shadow — fee 0.08% roundtrip (kinqo.com). Live капитал не ставится на rejected.
4. **Обучение.** Bayesian online + shrunk mean + Wilson LCB. Обновление фильтров каждые 6 часов (kinqo.com). v1.1: «Corrected shadow PnL formula» — формула тени в v1 была ошибочной.
5. **Исполнение.** «NON_CUSTODIAL ▲ VERIFIED» на сайте. Код ключей: **не обнаружено** в открытом git.

### C — «тень ускоряет обновление в 2 раза»

Abstract v1.1: «2× more parameter updates than real-only systems via shadow exploration». kinqo.com: «97.6% of all market signals are captured as shadow data, providing 2x more Optimizer iterations». Это **больше итераций оптимизатора**, не «в 2 раза быстрее сходимость параметра в секундах».

Таблица kinqo.com: Fixed 87 сделок WR 31.2%; Random 142 / 28.7%; Shadow-only 294 / 35.1%; Full 301 / 41.3%. p<0.01 Wilcoxon. Рецензируемого журнала нет (preprint, 0 citations на карточке).

**Оценки:** данные 4 · решение 5 · риск 7 (тень без капитала) · адаптация 8 · исполнение 3 · проверяемость 4 · результаты 5 (live 60 дней, без кода).

---

## 6. TraderBench (arXiv:2603.00285)

### A

Не торговая система, а бенчмарк. 4 секции × 25%: KR, AR, Options, Crypto. 6 MCP (SEC EDGAR temporal lock, Yahoo lookahead detection, sandbox, options, trading sim, risk). Crypto: 4 трансформа baseline → noisy (σ=2% + volume 3×) → meta → adversarial (ложные MA/RSI/MACD). Скор: return 35% + Sharpe 30% + WR 20% + MDD 15%.

### B — почему ~33 баллов

Abstract: **8 of 13** моделей ~33 на crypto, вариация <1 по трансформ. Тело: **7 of 12** моделей 32–34. Расхождение 8/13 vs 7/12 — внутри статьи. Смысл один: плоский профиль = фиксированная стратегия (buy-and-hold / почти не торговать). Extended thinking: KR +26, crypto **+0.3**, options **−0.1**. Judge-variance: crypto 0.3 пункта (метрики), KR 28.8.

Gemma3-27B: baseline 62.7 → noisy 34.2 (−28). «Robustness through inaction» vs «genuine resilience» — авторы прямо разделяют.

**Оценки (как бенчмарк):** данные 8 · решение n/a · риск n/a · адаптация n/a (объект оценки) · исполнение 6 (симулятор) · проверяемость 7 · результаты n/a.

---

## 7. Детекция манипуляций (не одна система)

| Метод | Источник | Заявленный результат | Код |
|---|---|---|---|
| Randomized signatures + IsolationForest | Akyildirim et al., arXiv:2201.02441 | F1 до 88%, unsupervised, датасет La Morgia | gitlab.ethz.ch/Syang/reservoir-anomaly-detection |
| EWMA + vol + пороги цены/объёма | arXiv:2503.08692 | лучше ловит низколиквид vs «голый» spike | **не обнаружено** |
| Markov-modulated Hawkes | Eur. J. Finance 2026, DOI 10.1080/1351847x.2026.2624485 | аномальные пачки сделок vs Markov-Poisson | **не обнаружено** |
| HDP+ rush orders | JIDM | P 96.4 / R 89.3 / F1 92.7 | **не обнаружено** |

LLD (IEEE ICBC 2023): метод signatures использует окна **до и после** пампа — «use of future data … prevents … on-line». F1=88% — офлайн-детекция, не входной фильтр живого стола.

---

## 8. Ближайшие «мультимодальные / событийные» (вместо несуществующего LLM-Trader)

**Janus-Q** (arXiv:2602.19919): 62 400 новостей, 10 типов событий, CAR; SFT + RL с Hierarchical Gated Reward. Акции, не криптофьючерсы.

**F2Agent** (arXiv:2608.05668): 4 агента (market/TA/news/sentiment) + adaptive fusion + consistency regularization. TSLA 148.41% в статье — бэктест, не live.

**MM-DREX** (arXiv:2509.05080): VLM-роутер (Qwen 2.5 72B) весит 4 экспертов (trend/reversal/breakout/positioning); SFT-RL. Датасет 62 актива 2017–2025. Снятие visual modality: TR 25.75%→20.11%, SR 1.63→1.21.

**GS-Fuse** (KDD 2026, arXiv:2605.28520): гейт открывает текст **только если** он даёт прирост vs TS-only (Granger utility). Симметричный fuse новостей — заявленная причина шума.

---

## 9. TradingAgents v0.3.1 (`TauricResearch/TradingAgents`)

Релиз: 2026-07-05, tag v0.3.1. Клон просмотрен.

### A — README / сайт

Роли: Fundamentals, Sentiment, News, Technical → Bull/Bear debate → Trader → Risk (aggressive/conservative/neutral) → Portfolio Manager. LangGraph. Память `~/.tradingagents/memory/trading_memory.md`. Рефлексия: realized return + alpha vs бенчмарк, 2–4 предложения, в промпт PM (`tradingagents/graph/reflection.py` строки 14–57).

### A — код

- Риск — **LLM-дебаты**, не числовой VETO. README строка 91: «order will be sent to the **simulated** exchange».
- `reflection.py`: один вызов quick_thinking_llm, без градиента.
- v0.3.1 FIX: Alpha Vantage look-ahead — fundamentals JSON string обходил dict-guard, future-dated reports текли в историю (#1115). News prompt рекламировал `get_news(query)` при инструменте по тикеру (#1116). Crypto sentiment: StockTwits `.X`, Reddit base symbol (#1113).
- Ключи биржи: **не обнаружено**. Это research CLI.

### Статья vs «BTC +20.25%»

Официальная таблица tauric.ai: AAPL TradingAgents CR 26.62%, ARR 30.50%, SR 8.21, MDD 0.91% (акции, не перпы).  
**+20.25% BTC** — Gate Research, 1h BTC/USDT **2026-02-01…2026-05-01**, vs B&H −7.89%, MDD −17.41% vs −27.06%. Авторы Gate сами пишут: 3 месяца, издержки/слиппедж/задержка не доказаны. Это не результат репозитория Tauric и не live.

**Оценки:** данные 6 · решение 6 · риск 3 (промпт) · адаптация 6 · исполнение 2 · проверяемость 8 · результаты 4 (акции paper + чужой BTC backtest).

---

## 10. FFRDM — не обнаружено. Аналог: `poliakarmai/bybit-ws` v7.1

Документ: `docs/ARCHITECTURE.md` (raw GitHub, версия 2026-06-28).

### Как устроен 7-фильтровый вход (код/доки, не «80–90%»)

Порядок Auto-Entry LONG (ARCHITECTURE.md):

1. MTF Confluence D+W+M  
2. Orderbook Imbalance  
3. Volume Confirmation  
4. **Entry Judge** (LLM Nemotron → DeepSeek, fail-closed, timeout 5s, cache 300s)  
5. Correlation (r>0.85 блок, r>0.70 ×0.5)  
6. Post-trade cluster (WR<40% блок)  
7. Risk Manager (CB, margin, max pos, banned)

Fail-open для 1–3 (пропуск фильтра, −10% score). Fail-closed для Judge и Risk. 3 падения Judge → CB на 1 час. Цифра «экономия 80–90% LLM» **в этом репозитории не обнаружена**. Экономия следует из того, что LLM — 4-й фильтр после трёх дешёвых; доля отсева до Judge в файле не опубликована.

Риск в коде (доки): max позиций 12 (NY 5 / Asia 10 / Weekend 3); max маржа $300; max daily −$50; Risk CB на 80% daily loss; Black Swan: PnL 2× limit **или** BTC −8%/час; JUNK: SL −15%, max $5, 2 слота, 2 стопа → off 24h. Self-learn каждые 2880 циклов (~24ч): min_score +30% при WR<40%, SL +20%.

Ключи: HMAC Bybit в `.env` chmod 600, тот же хост что и стратегия. Отдельного signer-процесса как у Capitalizator: **не обнаружено**.

**Оценки (bybit-ws):** данные 6 · решение 5 · риск 8 · адаптация 7 · исполнение 5 · проверяемость 7 · результаты 2 (нет публичного аудита PnL).

---

## 11. Quant Flow (`web3spreads/quant-flow`)

Прочитано: `docs/architecture.md`, `src/strategy/perp.py`, `src/llm.py`, `src/plugins/protections/manager.py`, `src/trading/order_manager.py`, `src/config.py`.

### A / C — как ошибка LLM не становится сделкой

Контракт в `perp.py` строки 8–13, 27–28, 108–155, 211–220:

- LLM → JSON `{action, confidence, amount_usd, leverage, reason}`.
- Не парсится / illegal action / нет amount|leverage на BUY/SELL_SHORT → **HOLD, `llm_ok=False`**. Исторический баг (комментарий 131–134): дефолт на max_trade_amount — **убран**.
- amount/leverage **clamp** на `max_trade_amount` / `max_leverage`.
- confidence < `min_confidence` → не исполнять.
- Запрет нового входа, дубль направления, **reverse без CLOSE** (net position Hyperliquid), max_positions, баланс.
- TP/SL считает код (`take_profit_ratio` / `stop_loss_ratio`), не LLM. SL fail → `emergency_close_with_retry`; если и rollback падает — `executed=True` чтобы account protections видели голый риск (`perp.py` 250–270).
- Triple Barrier сетки **независимо** от AI action, в т.ч. на KEEP_GRID/ERROR (`architecture.md`).
- Protections default (`config.py` 28–33): DD 10%, daily 5%, 5 лоссов/символ, timeout 48h. Severity: CLOSE_ALL > PAUSE_NEW.
- LLM consecutive fail → escalate alert (`_track_llm_health`).

**Ключи:** `HYPERLIQUID_PRIVATE_KEY` в env, тот же процесс что Engine (`config.py` 10–11, 151–164; `client.py` from_key). LLM ключ не подписывает ордера, но **изоляции signer нет**. Default testnet=true.

**Оценки:** данные 4 (индикаторы, без ончейна/новостей в ядре) · решение 5 · риск 9 · адаптация 3 · исполнение 6 · проверяемость 9 · результаты 1 (нет публичного PnL).

---

## 12. Onchain-AI-Hedge-Fund (`LoopGlitch26`)

### Статья/README vs код

README: «4-specialist ensemble (Technical, ML, Risk, Quant) with judge consensus».  
`ARCHITECTURE.md` рисует классы с «Predictive modeling / Statistical arbitrage».

**Код:** все четыре — LLM role-play через OpenRouter. `ml_analyst.py` строки 14–27: имя «Ray (Two Sigma Style)», `self.model = CONFIG["llm_model"]`, sklearn/torch **не импортированы**. Judge — ещё один LLM (`market_scanner.py` `_run_judge`).

Промпт судьи (`market_scanner.py` 167–209), дословно:

- «BTC/USDT only. Ignore all other assets.»
- «Position size: $16,000–$18,000 notional at 20x»
- «Leverage: 20x FIXED»
- «Stop loss: 1% … Take profit: 0.8–1.5%»

Это не консенсус по уверенности. Это LLM с зашитым скальпом 20x.

Ключи: `HYPERLIQUID_PRIVATE_KEY` в `.env` и **в GUI settings** (`settings.py` 281–380: «stored in data/config.json»). Цикл 5 минут. При отсутствии консенсуса — HOLD (`bot_engine.py` 452–464).

**Оценки:** данные 4 · решение 3 · риск 2 (20x в промпте) · адаптация 2 · исполнение 2 · проверяемость 6 (код открыт, расхождение с README) · результаты 1.

---

## 13. Quant 2.0 (229 рынков / 15 мин / 5× вес)

**не обнаружено** как публичная система с этими тремя признаками. Ближайшие чужие факты: FreqAI ретрейн в фоне (freqtrade docs); Alcyone — nightly CPCV, не 15 мин; «5×» в чужих README = плечо, не вес лосса. В матрицу как продукт не входит.

---

## 14. MAHORAGA (`ygwyg/MAHORAGA`)

### A — README

Durable Object + D1 + KV; StockTwits, Reddit ×4, Twitter confirm, SEC; LLM via AI SDK; исполнение **Alpaca**; crypto opt-in; defaults: max 5 поз, $5000/поз, TP 10%, SL 5%, min sentiment 0.3, min LLM conf 0.6, daily loss 2%, no margin, no short. Kill switch отдельным секретом.

### A — код

`policy/engine.ts` 4–21, 55–75: kill switch, cooldown, daily loss, hours (crypto skip), allow/deny, notional, % equity, max positions, short block, buying power.  
`core/policy-broker.ts` 1–9: **H2** — harness раньше звал `alpaca.trading.createOrder()` в обход policy; теперь buy/sell только через `PolicyEngine.evaluate()`. Approval token TTL 5 мин (комментарий engine.ts 20–21).

Ключи: Cloudflare secrets + Alpaca API (брокер кастодирует). LLM решает вход; policy — пост-фильтр. Перпы Bybit: **не обнаружено**.

**Оценки:** данные 6 (соц.) · решение 4 · риск 8 · адаптация 4 · исполнение 7 (DO+kill+H2) · проверяемость 8 · результаты 1.

---

## 15. Alpha Arena Season 1 (nof1, 2025)

Сводка, согласованная SCMP + GuruFocus + RootData + iweaver + ForkLog (пост Jay A. Zhang):

| | |
|---|---|
| Старт / длина | 2025-10-18, 17 дней (GuruFocus) |
| Рынок | Hyperliquid USDT-перпы, $10 000 на модель |
| Вход | одинаковые промпты и данные (iweaver, со ссылкой на организатора) |
| Кто решает риск | **сама модель**: выбор, сайз, тайминг, риск (iweaver) |

| Место | Модель | Доходность |
|---|---|---|
| 1 | Qwen3-Max | **+22.32%** (SCMP / GuruFocus) |
| 2 | DeepSeek Chat V3.1 | **+4.89%** (RootData / iweaver) |
| 3 | Claude Sonnet 4.5 | **−30.81%** |
| 4 | Grok 4 | **−45.3%** |
| 5 | Gemini 2.5 Pro | **−56.71%** |
| 6 | GPT-5 | **−62.66%** (SCMP) |

RootData: Qwen 43 сделки, WR 30.2%; DeepSeek 41, WR 24.4%. ForkLog/Zhang: финальные балансы ≈ $12 231 / $10 489 / $5 799 / $5 445 / $4 208 / $4 126.

Вторичные блоги (BestHub, osaengine) публикуют **другие** числа (GPT-5 −72%, 203 сделки и т.д.). Они **не согласованы** с SCMP/RootData и в таблицу не входят.

### B — почему GPT-5 слил, Qwen заработал

Факт постановки: риск и сайз **в промпте модели**, не в детерминированном ядре (iweaver).  
Заявленный разбор nof1 в пересказе Sandmark: Qwen — «aggressive conviction with tight stop-loss discipline»; GPT-5 / Gemini — «prompt-induced hesitation» и частые развороты.  
iweaver прямо пишет: лидерборд **не изолирует** одну причину (направление / сайз / выход / овертрейд / промпт / режим).

Вывод для инженерии, опирающийся только на постановку: при идентичных данных победила **дисциплина исполнения внутри модели**; у четырёх из шести моделей этой дисциплины не хватило. Это аргумент **против** «отдать LLM ключ и риск», не аргумент «Qwen умнее GPT-5 в трейдинге вообще».

---

## 16. AriseAlpha

GlobeNewswire 2026-05-19 (MEXC/Crypto-Reporter): 40+ переменных; режимы bull (больше сайз, дольше hold) / bear (теснее SL, меньше плечо) / range (mean-reversion + scalp); внутренний 90-day backtest Q1 2026 — «static bots double-digit DD, we captured 70%+ upside».

Particle.news и WalletInvestor: цифры **внутренние, без third-party**. WalletInvestor: публичные планы 1.4–2.6% в день, «returns unchanged when volatile», pooled funds — это маркетинг депозитного продукта, не описание ядра.

Код, параметры 40 переменных, ключи: **не обнаружено**.

**Оценки:** данные 2 · решение 2 · риск 1 · адаптация 2 · исполнение 1 · проверяемость 1 · результаты 1.

---

## 17. Fere AI

GlobeNewswire 2026-04-23: $1.3M, lead Ethereal Ventures, Galaxy Vision Hill, Kosmos. Сети ETH/SOL/Base/Arbitrum/BNB + Polymarket. Заявлено 10M agent actions. «Reinforcement learning … against live market environments» — в пресс-релизе. docs.fereai.xyz: CDP Server Wallets (Coinbase). MCP в ChatGPT/Claude.

Открытый код RL, параметры, Bybit-перпы: **не обнаружено**. Ключ: custodial CDP wallet, не локальный signer.

**Оценки:** данные 5 (ончейн+соц по докам) · решение 3 · риск 2 · адаптация 3 (декларация) · исполнение 4 (CDP) · проверяемость 2 · результаты 2.

---

## 18. OneBullEx / OneALPHA / 300 SPARTANS

PR Newswire 302727385 + ChainCatcher 2026-05-22: три слоя — биржа / 300 SPARTANS (правила после walk-forward) / OneALPHA (NL → 5 агентов → код → WFO, glass-box). «50+ пар» из пользовательского списка в этих PR **не подтверждено** («multiple perpetual pairs»).

Код агентов, критерии WFO, живой PnL: **не обнаружено**.

**Оценки:** данные 2 · решение 3 · риск 2 · адаптация 3 · исполнение 3 · проверяемость 2 · результаты 1.

---

## 19. HydraQuant (доп. OSS, не из списка)

`ymcbzrgn/HydraQuant`: Evidence Engine — 6 подвопросов (trend/momentum/crowd/history/macro/stability) <50 ms **без LLM**; затем 4–7 из 12 агентов в дебате; 9-стадийный Bayesian sizing; Bybit/Binance testnet first. Это открытый префильтр «сначала дешёвые правила», близкий по духу к запросу про FFRDM.

---

# Часть 2. Матрица (1–10)

Шкала: 1 = нет/маркетинг; 10 = задокументировано в коде или в рецензируемой постановке с аудитом. «Реальные результаты» = публичная торговля деньгами или live-арена, не бэктест.

| Система | Данные | Решение | Риск (код vs промпт) | Адаптация | Исполнение | Проверяемость | Live/реал |
|---|---:|---:|---:|---:|---:|---:|---:|
| CryptoNewsTrade | 6 | 5 | 2 | 4 | 1 | 2 | 3 |
| Fin-Analyst | 7 | 6 | 3 | 2 | 4 | 7 | 6 |
| CryptoTrade | 6 | 5 | 2 | 5 | 2 | 8 | 4 |
| Meta-RL-Crypto | 6 | 6 | 3 | 7 | 1 | 3 | 3 |
| ARTEMIS | 4 | 5 | 7 | 8 | 3 | 4 | 5 |
| TraderBench | 8 | — | — | — | 6 | 7 | — |
| Signatures P&D | 5 | — | — | — | — | 6 | — |
| TradingAgents v0.3.1 | 6 | 6 | 3 | 6 | 2 | 8 | 4 |
| bybit-ws (аналог FFRDM) | 6 | 5 | 8 | 7 | 5 | 7 | 2 |
| Quant Flow | 4 | 5 | **9** | 3 | 6 | **9** | 1 |
| Onchain-AI-HF | 4 | 3 | 2 | 2 | 2 | 6 | 1 |
| MAHORAGA | 6 | 4 | 8 | 4 | 7 | 8 | 1 |
| Alpha Arena (6 LLM) | 3 | 4 | **1** | 1 | 3 | 7 | **8** |
| AriseAlpha | 2 | 2 | 1 | 2 | 1 | 1 | 1 |
| Fere AI | 5 | 3 | 2 | 3 | 4 | 2 | 2 |
| OneALPHA | 2 | 3 | 2 | 3 | 3 | 2 | 1 |
| GS-Fuse | 7 | 6 | — | 5 | — | 6 | — |
| Janus-Q / F2Agent / MM-DREX | 7 | 6 | 3 | 6 | 1 | 4 | 3 |

Читать матрицу так: **лучшие из открытого кода по риску/аудиту — Quant Flow и MAHORAGA policy + bybit-ws filters**. **Единственный крупный live с деньгами — Alpha Arena**, и он же худший по риску (риск в модели). Научные LLM-агенты сильны в декларации данных и слабы в исполнении.

---

# Часть 3. Рекомендации для Capitalizator

Канон, с которым сверены советы: `docs/PRODUCT.md`, `docs/ARCHITECTURE-AZ.md`; ядро A = зона × 8с ZLG/PRS/OFI × CAV × Accord-or-Silence; B = veto|hold|propose|cut_size; C = тень + экзамен без авто-promote; ОКО = нормы символа, не новости; ключ только у signer; Limit+PostOnly, `slTriggerBy=MarkPrice`; нет RL/PPO/LSTM в ядре.

**Не предлагается и не является дырой:** RL на исполнении; EWMA-края зоны; удаление `WhalePit.accept()==False`; Glassnode в паспорт ОКО.

## 1. Настоящие преимущества (комбинации, которой нет ни у одной разобранной системы)

1. **Позвоночник микроструктуры.** Ни TradingAgents, ни Quant Flow, ни CryptoTrade, ни Fin-Analyst, ни Alpha Arena не строят вход как «зона заранее × 8-секундная книга × CAV на закрытии рабочего бара × Accord-or-Silence». У них либо дневной LLM, либо индикаторы на закрытии свечи, либо соц. сентимент. 8с ZLG/PRS/OFI как условие ордера в этом корпусе **не обнаружено**.
2. **Accord-or-Silence ≠ majority и ≠ LLM-judge.** Fin-Analyst Meta при ≥5 голосах торгует; Onchain-judge — ещё один LLM с 20x в промпте; TradingAgents PM — LLM. Молчание при расколе — отдельный вид, ближе к «HOLD if split» Fin-Analyst, но у вас раскол **убивает сделку**, а не отдаёт её мета-агенту.
3. **ОКО как шестой голос нормы символа.** Паспорт (depth, spread_ticks, print_qty, prints_per_s, range, OI, funding, churn, n≥30) — не ончейн и не новость. Ближайший чужой объект — TraderBench noisy-transform и Oko-подобные microstructure gates **не найдены** как отдельный veto-слой.
4. **Ключ не у LLM и не в том же «мозге».** Quant Flow и Onchain грузят `HYPERLIQUID_PRIVATE_KEY` в процесс стратегии. MAHORAGA отдаёт ключ Alpaca. Fere — CDP wallet. У вас `intent_queue` → signer (`PRODUCT.md` закон 6, «ИИ с ключом» запрещён). Это строже, чем «LLM не вызывает SDK», потому что процесс с ключом отделён.
5. **Контур B не голосует в жюри.** HACK/CPI/FOMC → veto/cut; `sole_whale` → hold; месячный F&G → только `size_mult`. Fin-Analyst вшил F&G в **голос** BTC. CryptoTrade вшил новость в trading agent. У вас новость не открывает сайз.
6. **Контур C без автопереворота стола.** ARTEMIS и bybit-ws self_learn правят пороги сами. У вас exam пишет `exam_last` / `champion_candidate`, стол не флипается. Это закрывает класс «оптимизатор съел чемпиона на 60 днях».
7. **Исполнение maker + Mark SL.** Alpha Arena и Onchain оставляют выход модели. Quant Flow вешает ratio-TP/SL. У вас Limit+PostOnly и `slTriggerBy=MarkPrice` (`gateway/bybit.py` 384–389) — отдельный класс защиты от wick/index.
8. **Один код-путь off|learn|demo|live и запрет усреднения.** bybit-ws имеет DCA overlay. MAHORAGA options averaging-down блок есть, но спот/опционы. Закон «нет усреднения» как инвариант ядра в этом корпусе **не обнаружен**.

## 2. Опасные слепые зоны (у других доказано, у нас нет; без ломки ядра)

| Слепая зона | Где доказано | Почему это не «внедрить RL» |
|---|---|---|
| **Память серии ошибок B** | Fin-Analyst §6.1: memoryless 6 дней подряд держал неверный short | Журнал B: «этот veto/hold уже N дней совпадает с против нас» → не ослабляет A, режет повторный propose |
| **Новость только если даёт прирост** | GS-Fuse: гейт текста vs TS-only; Fin-Analyst 10-K/Compustat **вредят** дневному горизонту | Календарь B уже veto. Нет теста «этот заголовок добавляет к зоне+книге». Без заталкивания RSS в ОКО |
| **Детект пампа как B-veto** | EWMA 2503.08692; HDP+ F1 92.7; signatures 88% офлайн | Только альты, только veto/cut_size, не голос жюри и не паспорт ОКО |
| **Тень отклонённых B-сигналов** | ARTEMIS: 97.6% сигналов в shadow, 2× итераций оптимизатора; WR 31.2→41.3 на 301 сделке | У вас C = тень **претендента стратегии**. Нет тени «жюри сказало нет / B veto». Счётчик без авто-promote |
| **Префильтр до вызова LLM B** | bybit-ws: 3 дешёвых фильтра до Judge; HydraQuant Evidence <50 ms | B дорогой. Если нет HACK/CPI и книга пустая — не звать LLM. Не трогает A |
| **SL не встал → flatten** | Quant Flow `emergency_close_with_retry`; голая позиция помечается executed | Закрыто `70f598f` (desk OMS, не signer). Не жюри |
| **Look-ahead в intel** | TradingAgents v0.3.1 #1115: future filings в истории | Point-in-time штамп «когда узнали» для B (у вас в ARCHITECTURE-AZ уже как закон знаний) — добить тестами |
| **Одинаковый промпт + LLM-риск = рулетка** | Alpha Arena: 4/6 моделей в глубоком минусе на тех же данных | Уже закрыто архитектурой. Слепая зона — если B начнут просить «немного сайза» |
| **Нет публичного live-доказательства** | Alpha Arena / Fin-Analyst арена | Стол частный; слепая зона доверия, не альфы |
| **Одна биржа, 10 символов** | — | Не дыра ядра; ограничение вселенной |

Не слепые зоны: отсутствие PPO/LSTM; отсутствие ончейна в ОКО; `WhalePit.accept()==False`.

## 3. Что взять за 1 месяц (только контур B / gateway / C-учёт)

1. **Префильтр B (3–5 дней).** Перед LLM-карточкой: пустой календарь HACK/CPI/FOMC → не звать новостной LLM; `min(Oko.n)<30` уже режет; корреляция/лимит идей — уже в риске. Образец порядка: bybit-ws фильтры 1–3 до Judge. Цель — стоимость B, не новое правило входа A.
2. **Журнал серии промахов B (3–5 дней).** Как Fin-Analyst группа 2: если veto/hold N дней расходится с закрытым paper R — флаг в карточке, без автоослабления A.
3. **Тень отвергнутых касаний (1–2 недели).** Как ARTEMIS, но **только учёт**: `would_have_R` для «жюри молчит» и «B veto». Писать в exam, не в promote. Wilson LCB на ведро (символ × окно × причина отказа) — у ARTEMIS v1.1 и в FMZ-разборе shadow buckets.
4. **Аудит trading-stop.** ~~Дыра «запрос ушёл, биржа не подтвердила».~~ Закрыто в `70f598f`: стол делает OMS `amend_stop` (`sl_retry`), на следующем reconcile — `flatten` (`sl_unconfirmed`). Signer по-прежнему не выходит сам.
5. **Pump EWMA на 8 альтах как B-veto (1 неделя).** Пороги из arXiv:2503.08692 (цена vs EWMA + объём + vol). Не Hawkes в ядре. Не signatures с будущим окном (LLD).
6. **PIT-тесты intel (3 дня).** По образцу TradingAgents #1115: заголовок с `published_at > decision_ts` не входит в карточку.
7. **Не брать:** Actor-Judge-Meta-Judge; 20x в промпте; F&G как голос жюри; DCA bybit-ws; авто-self_learn порогов A; Fine-tune Llama на α_t.

## 4. Дорожная карта 3–6 месяцев

| Срок | Этап | Зачем | Риск этапа |
|---|---|---|---|
| Месяц 1 | Префильтр B + серия ошибок + SL-ack flatten + PIT-тесты | Дешёвый контур B, закрыть Fin-Analyst/Quant Flow/TradingAgents дыры | Ложный B-veto режет частоту. Лечится тенью отвергнутых, не откатом жюри |
| Месяц 2 | EWMA pump как B-veto на альтах; календарь уже есть | Слепая зона манипуляций на DOGE/SUI и т.п. | Порог с чужой бумаги не калиброван на Bybit linear — только paper |
| Месяц 3 | Тень отвергнутых + Wilson LCB в exam C | ARTEMIS-урок без авто-promote | Оператор начнёт «чуть-чуть флипать» по LCB — запретить в коде promote |
| Месяцы 4–5 | Granger-тест для **класса** события (не для ОКО): CPI/FOMC уже veto; RSS-шум — только если класс даёт прирост к paper R vs A-only | GS-Fuse + Fin-Analyst 10-K | Не впускать сырой текст в позвоночник |
| Месяц 6 | Расширение вселенной / второе окно сессии **только после** exam C на закрытом paper R | Gate Research сами пишут, что 3 месяца BTC backtest не генерализуется | Не копировать 229 рынков и 15-минутный ретрейн — объекта нет и он ломает закон «нет RL» |

Приоритет: **не интеллект модели, а изоляция риска** (Alpha Arena) + **память промаха** (Fin-Analyst) + **учёт отвергнутого** (ARTEMIS) + **дешёвый фильтр до LLM** (bybit-ws). Ядро A не трогать.

---

## Краткие ответы на фиксированные «почему»

1. **GPT-5 −62.66% vs Qwen +22.32%.** Постановка nof1: одинаковые данные, риск у модели (iweaver, SCMP). Организаторский пересказ: Qwen держал стоп, GPT-5 крутил позицию (Sandmark). Лидерборд не доказывает «архитектуру интеллекта» — доказывает, что LLM-риск на перпах за 17 дней даёт разброс от +22% до −63%.
2. **FinMMEval: окна и память.** Interim→final разворот TSLA/BTC (§5.2). Memoryless повтор short (§6.1).
3. **TraderBench ~33.** Фиксированная / инертная стратегия на 7–8 моделях; thinking не переносится в торговлю (+0.3).
4. **Новости шумят.** GS-Fuse: симметричный fuse без теста прироста. Fin-Analyst: 10-K и Compustat дают +CR при отключении. CryptoNewsTrade цифры 80.46%/7.83 без кода не проверяются.

**Менять ядро Capitalizator по итогам этого обзора нечего.** Заимствования — только B/C-учёт и gateway-ack.

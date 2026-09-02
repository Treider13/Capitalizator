# Capitalizator

Частная фьючерсная торговая система. Исследования и план — в `docs/`.  
Код: рекордер (pybit public WS → parquet part-файлы), книга/ресинк, реестр инструментов, стол 24/7 (зоны → касание → ZLG/CAV → жюри → **бумажное исполнение** тени/демо с комиссиями), риск-движок (эквити, размер, EV-гейт, краны, бюджет), умный стоп и трейл, шлюз Bybit v5 (pybit) с OMS-очередью, консоль с эквити/позициями/баннерами. Живой VPS/сутки и testnet-hello **ещё не зелёные** (`ops/STATUS.md`). Аудит и карта исправлений: [`docs/AUDIT-2026-09-02.md`](docs/AUDIT-2026-09-02.md).  
База на ноут и переезд: [`docs/VAULT-LAPTOP.md`](docs/VAULT-LAPTOP.md).

**С чего читать:** [`docs/PHASE-BUILD.md`](docs/PHASE-BUILD.md) — очередь шагов плюс детализация (артефакты, глоссарий, SQL гейтов, тесты, мониторинг, окна UTC).  
Архитектура модулей: [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).  
Фазы, гейты и деньги: [`docs/PHASES-ALL.md`](docs/PHASES-ALL.md).  
Стол команды: [`docs/TEAM-DESK.md`](docs/TEAM-DESK.md).  
Нейтральный месяц при скальпе 5% по очереди: [`docs/VERDICT-SCALP-5PCT.md`](docs/VERDICT-SCALP-5PCT.md).  
100k → 600–900k при 10% в сделке: [`docs/VERDICT-600-900.md`](docs/VERDICT-600-900.md).  
**Что делать, чтобы целиться в 900k:** [`docs/PLAN-900k.md`](docs/PLAN-900k.md).  
«Со 100к по 10к в день»: [`docs/VERDICT-10K-DAY.md`](docs/VERDICT-10K-DAY.md).  
50к в месяц со 100к: [`docs/VERDICT-50K-MONTH.md`](docs/VERDICT-50K-MONTH.md).  
Альты + шире стоп / больше маржа: [`docs/ALTS-MARGIN-STOP.md`](docs/ALTS-MARGIN-STOP.md).  
Трейл и альт +40%: [`docs/TRAIL-RUNNERS.md`](docs/TRAIL-RUNNERS.md) — хвост ловим остатком, не бюджетом.  
Почему худой месяц бывает у умного стола: [`docs/WHY-BAD-MONTH.md`](docs/WHY-BAD-MONTH.md).  
Как стать первыми в мире честно: [`docs/FIRST-IN-WORLD.md`](docs/FIRST-IN-WORLD.md) — стол исходов, не самый большой PnL.  
Пассивное восстановление стакана (не Sharpe > 3): [`docs/PASSIVE-RESILIENCE.md`](docs/PASSIVE-RESILIENCE.md).  
Изобретение: жест книги и первый факт: [`docs/INVENTION-FIRST-FACT.md`](docs/INVENTION-FIRST-FACT.md).  
Жюри графика и книги, % за час сессии: [`docs/INVENTION-JURY.md`](docs/INVENTION-JURY.md).  
ICT + «поток заказов» vs наши атомы: [`docs/COMPARE-ICT-FLOW.md`](docs/COMPARE-ICT-FLOW.md).  
×6–×9 за 6 месяцев «стабильно и с низким риском»: [`docs/VERDICT-x6-LOWRISK.md`](docs/VERDICT-x6-LOWRISK.md) — **нет**.

Рядом: [`docs/SR-LEVELS-SCIENCE.md`](docs/SR-LEVELS-SCIENCE.md) (факты по уровням), [`docs/CENSUS-PRACTICE-REPOS.md`](docs/CENSUS-PRACTICE-REPOS.md) (~110 репо), [`docs/ARCHITECTURE-AZ.md`](docs/ARCHITECTURE-AZ.md) (ИИ, безопасность, контуры).

Кто реально прибыльный на **криптофьючерсах** (не звёзды): [`docs/FUTURES-BOTS-RESULTS.md`](docs/FUTURES-BOTS-RESULTS.md).  
Перепись **150** топовых ботов/движков против стола (вечер 30.08): [`docs/CENSUS-150.md`](docs/CENSUS-150.md).  
Мировой поиск (CN/IN/JP/KR, языки, Gitee/GitLab): [`docs/WORLD-SEARCH.md`](docs/WORLD-SEARCH.md) — пустой продукт пуст не только на EN GitHub.  
Утренняя перепись практики (~110, issues/PnL): [`docs/CENSUS-PRACTICE-REPOS.md`](docs/CENSUS-PRACTICE-REPOS.md).

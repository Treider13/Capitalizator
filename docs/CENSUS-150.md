# Перепись 150: топовые боты GitHub против стола Capitalizator

**Дата:** 2026-08-30 (вечер) · Живые ★ / issues / `pushedAt` через GitHub Search API и `gh repo view`.  
Предыдущая перепись практики (~110, утро): [`CENSUS-PRACTICE-REPOS.md`](CENSUS-PRACTICE-REPOS.md). Здесь — **вторая волна**: шире (150 уникальных), глубже по топам, и каждый класс сверстан с **нашими законами**, не со звёздами.

**Метод.** ~25 поисковых запросов (`crypto trading bot`, `futures`, `grid`, `bybit`, `passivbot`, `order book`, `smart-money-concepts`, `hyperliquid bot`, `topic:trading-bot`, `llm trading` через awesome-листы). Списки: `botcrypto-io/awesome-crypto-trading-bots` (2496★), `LLMQuant/awesome-trading-agents` (436★), `wilsonfreitas/awesome-quant` (29319★). Плюс ручной проход утренней переписи. Отсеяны Runescape-боты, кристаллическая «Wyckoff» (группы симметрии), AWS-курсы, NiceHash-вставки.

Цифры результата на фьючерсах (не звёзды): [`FUTURES-BOTS-RESULTS.md`](FUTURES-BOTS-RESULTS.md).

**Теги PnL (как утром):** `[V]` третья сторона / ончейн · `[S]` автор или юзер с деталью · `[M]` маркетинг / скрин · `—` нет.

**Вердикт «нам»:** `позвоночник` / `труба` / `учить` / `антипример` / `игнор` / `пусто` (идея есть, продукта нет).

---

## 0. Что у нас есть — и чего на GitHub нет

Мы не ищем «ещё один Freqtrade». Мы ищем, **занято ли поле стола**. Кратко, что уже решено в репо (не переоткрывать):

| Наш закон | Где записан | Что GitHub гоняет вместо этого |
|---|---|---|
| Свой счёт Bybit/MEXC, не проп, не копи | `PHASES-ALL`, `IMPLEMENTATION` §2 | Копи HL-кошелька, TV-webhook «нажми за меня», проп-мечты |
| Нет `average_in` / грид / мартингейл | схема риска, гейты | **Именно это** люди крутят: NFI grind, passivbot, OctoBot Grid, OpenTrader GRID/DCA |
| Зона заранее, не линия; отскок vs пробой | роль 1, `SR-LEVELS-SCIENCE` | Калькуляторы POC/VP и SMC-либа с lookahead. Бота с пользователями нет |
| Стена без ленты ≠ вход; PRS/ZLG после *чужой* сделки | роли 2, изобретения | Визуализаторы footprint. Практический «order flow» OSS = **маркет-мейкинг** (быть в книге), не читать её |
| BTC-вето на альт (закрытие + поток) | роль 3 | Issue Haehnchen [#358](https://github.com/Haehnchen/crypto-trading-bot/issues/358) просят годами. Репо «BTC filter» почти нет |
| Карточка VERIFIED из PIT-SQL; LLM без ключей, ≥60 с | роли 4–5, контур B | TradingAgents: дебаты без ордера. nofx: LLM **шлёт** ордер, ключи утекали |
| 10% = маржа, риск ≈1.2% после гейта; 50% на +1R | риск | Ритейл-боты считают «10% в сделку» как риск или усредняют |
| Первые = реестр зона×жест×исход, не PnL | `FIRST-IN-WORLD` | Такого продукта нет. Формулу скопируют, таблицу — нет |

Пустое пересечение **не изменилось** за вечернюю волну: живой перп-стол «зона + жест книги + BTC-вето + карточка + риск без доливки» как репозиторий с чужими issues **не появился**.

---

## 1. Заголовок одним абзацем

Звёзды 2026 года — это **LLM-театр** (TradingAgents 101 873★ без исполнения) и **движки** (Freqtrade, Nautilus, Hummingbot). Деньги людей на GitHub по-прежнему крутят **грид / DCA / grind**. Направление «зона / отскок / стакан / BTC» остаётся библиотеками и графиками. Единственный посчитанный фьючерсный край в этой выборке — research по фандингу (`funding-rate-alpha`, 8.9 б.п./день). Для нас это значит: позвоночник брать у Nautilus, трубы у Tardis/cryptofeed/ccxt/pybit, риск-кламп смотреть у nofx как **антипример ключей**, стратегии NFI/passivbot **не** переносить.

---

## 2. Глубокий разбор: кто реально формирует поле

Ниже не «ещё одна строка в таблице», а зачем проект существует и что из него **нельзя** перенести в Capitalizator.

### 2.1. Движки (код-путь, не край)

**Freqtrade** (53843★, 34 open, пуш сегодня). Доминирующий ритейл-бот: свечи → стратегия Python → Telegram. Люди **не** торгуют официальные сэмплы (`freqtrade-strategies` 5419★: «all strategies make crap profits» [#333](https://github.com/freqtrade/freqtrade-strategies/issues/333)). Гоняют **NostalgiaForInfinity**. Нативного walk-forward нет — мейнтейнеры отказали ([#11737](https://github.com/freqtrade/freqtrade/issues/11737)). Поэтому у нас позвоночник **не** Freqtrade. Учить: культура dry-run, pairlists, документация комиссий.

**NautilusTrader** (28153★, 111 open, пуш сегодня). Rust-ядро, один путь replay/backtest/live, crash-only. Примеры — типы ордеров и адаптеры, **не** зона/жест. Это наш канон ядра (`IMPLEMENTATION` §5). Не ждать от апстрима стратегии стола.

**Hummingbot** (19708★, 154 open). Маркет-мейкинг и арбитраж, CEX+DEX. Публичные скрипты — PMM / VWAP / arb. Это **исполнение в книге**, не отскок от зоны. На 10k маржи нам не нужен их PMM. Учить: коннекторы, разделение стратегии и ключа (у них лучше, чем у LLM-ботов).

**Jesse** (8397★, 16 open). Исследовательский фреймворк свечей. Live — платный плагин. Примеры EMA/RSI. Не стол.

**QuantConnect Lean** (21417★, 259 open). Институциональный движок, крипта возможна. Тяжёлый, C#/облако. Не наш стек на VPS у Bybit.

**OctoBot** (6494★, 166 open). Потребитель: Grid / DCA / TradingView / «LLM evaluator». Живые issues про комиссии грида live≠backtest [#3656](https://github.com/Drakkar-Software/OctoBot/issues/3656). Антипример продукта: то, что продаётся UI, мы сознательно вырезали.

**OpenTrader** (2841★, last meaningful 2025-06). Self-host GRID+DCA, 100+ бирж через ccxt. Тот же класс, что OctoBot, моложе, меньше практики.

**bbgo** (1657★, 133 open). Go. Пользователи крутят **grid2** (застревает после стопа [#1764](https://github.com/c9s/bbgo/issues/1764)). Движок годный, стратегия — грид.

**Superalgos** (5632★, 113 open). Визуальный конструктор. Форков больше, чем смысла (токен-стимул). Не край.

**StockSharp** (10667★). C# терминал, больше акции/фьючерсы РФ/мир, не наш Bybit-стол.

**gocryptotrader** (3456★). Биржевой клиент на Go, не стратегия.

**pybroker / blankly / lumibot / basana / ninjabot / the0 / NexusTrader / go-trader / Cassandre.** Второй эшелон фреймворков. Ни один не закрывает зону×жест×BTC. `the0` (411★) — контейнер «напиши стратегию на чём угодно»: оркестратор, не мозг.

### 2.2. То, что люди реально гоняют (и что нам запрещено)

**NostalgiaForInfinity** (3383★, 82 open, пуш сегодня). Стратегия Freqtrade: X7 **grind/DCA**. Не S/R, не SMC. Усреднение в минус. Живые жалобы: fills на топах, $440 сетапы, гринд у ликвидации, backtest≠live. Discord — настоящая община. `[S]` смешанный. **Антипример №1.** Наша старая схема 30k+доливка — родственник этого класса. Код должен отвергать, не «вдохновляться сайзингом».

**passivbot** (2085★, 80 open). Рекурсивный грид/трейл на перпах Bybit/OKX/Binance/Bitget/HL. Владелец чинит live-баги (deadlock рестарта, двойной баланс UNIFIED). Конфиги — отдельная индустрия (`PassivBot-Configurations` 124★). В диапазоне печатает, в тренде сносят. **Антипример №2.**

**Haehnchen/crypto-trading-bot** (3516★, 120 open). JS, dip-catcher + TA, фьючи. Годы операционных issues. **Единственный топ, где люди явно просят BTC-фильтр на альт** [#358](https://github.com/Haehnchen/crypto-trading-bot/issues/358) — и не получают измеренного режима. Мы как раз этот фильтр **пишем и меряем**. Учить: как не надо — флаг без таблицы исходов.

**ctubio/K** (3709★, 64 open, пуш 2024-12). C++ скальп-MM. Люди ещё компилируют («is this dead?» [#1188](https://github.com/ctubio/Krypto-trading-bot/issues/1188)). На 10k маржи наш импакт мал; их урок — стопы на бирже и скорость cancel, не двусторонние котировки.

**51bitquant/binance_grid_trader** (975★). CN-сетка спот+фьючи. Операционные issues (tick size, hedge, плечо). Грид.

**chrisleekr/binance-trading-bot** (5548★, пуш сегодня). Дашборд + плюг-стратегии на Binance. Звёзды ≫ глубина края. Смотреть как UI-обёртку, не как стол.

**pycryptobot** (2057★). TA-бот, жив умеренно. Свечи.

**intelligent-trading-bot** (1864★, пуш сегодня). ML + фичи → сигнал. Research/prod гибрид, не зона.

**alpha-rptr** (691★). Мультибиржа фьючи, живой баг SL/TP. Плагин-стратегии свечного класса.

**kuegiBot** (120★). Личный бот «чтобы не отходить от правил». Ближе к нам по *мотиву* (дисциплина), не по микроструктуре.

**Mtemi Bybit+TradingView webhook** (518★). ТВ жмёт, бот ставит. Это **не** стол: роль 4 у нас не имеет права на ордер.

**Adamant-tradebot** (848★). Сеточный/трейлинг мессенджер-бот. Не наш контур.

**TV-Webhook-Bot (fabston)** (1849★). Инфра алертов. Можно украсть идею «карточка на экране до входа», не «алерт = market».

### 2.3. LLM-слой (звёзды врут сильнее всего)

**TradingAgents** (101 873★, 377 open). Ролевая игра аналитиков. Авторский BT: 3 акции, 1 квартал, Sharpe 8.21. Независимый прогон в нашей сессии: **−25.4%**. Исполнения ордеров нет. Форки: CN 31476★, AShare 804★ — те же дебаты про A-shares. **Нам:** контур B может спорить; контур A — никогда. Не подключать «трейдера» агента к signer.

**ai-hedge-fund** (63099★). Персоны Баффет/Бьюрри, paper. Крипто-форк `51bitquant/ai-hedge-fund-crypto` (619★) — тот же театр на монетах.

**OpenBB** (72508★). Дата-платформа, не бот. Не конкурент.

**AI-Trader / FinRL / FinGPT / FinRobot / QuantDinger / valuecell / RD-Agent.** Арены, бенчмарки, «платформы». Нет книги зона×жест.

**nofx** (12786★, **518** open). Единственный массовый OSS, где LLM **может отправить** ордер, а Go-рантайм клампит размер. Пользователи пытаются live. SlowMist: утечка API-ключей. **Учить:** кламп размера в коде, не в промпте. **Не повторять:** ключ в зоне LLM, egress с недоверенным текстом (у нас EchoLeak-карантин).

**LLM-TradeBot** (315★), **OpenAlice**, **Vibe-Trading**, туториалы FareedKhan. Волна после Alpha Arena. 0 верифицированных книг.

### 2.4. Микроструктура и «умные деньги»

**smart-money-concepts** (1966★, 29 open). Единственная импортируемая SMC-либа. Lookahead в `swing_highs_lows()` [#101](https://github.com/joshyattridge/smart-money-concepts/issues/101) — бэктесты нарисованы. Мы **не** рисуем OB/FVG как истину.

**py-market-profile** (404★, stale). Калькулятор POC/VAH/VAL. Люди спорят с TradingView. Гипотеза зоны — да; вход — нет.

**hftbacktest** (4565★) + **cryptofeed** (2890★) + **Tardis** (147/366/310). Это то, чем пользуются серьёзные order-flow люди. Нам: трубы и реплей L2, не стратегия.

**DeepLOB / TLOB / LOBFrame / crypto-rl / Avellaneda–Stoikov.** Бумага. DeepLOB: утечка лейблов (уже в `market-analysis.md`). AS — MM, не отскок.

**Footprint-репо** (OrderflowChart, stack-orderflow, heatmap): графики. Вопрос «будет ли realtime?» — да, и на этом всё.

### 2.5. Единственный посчитанный край

**funding-rate-alpha** (39★). 6.1M настроек, без выживаемости. Торгуемый вариант **8.9 б.п./день, Sharpe 1.42** (уже в `market-analysis.md`). Это не наш сетап (окно 16:30–19:30, зоны). Можно держать как **скринер/вето** «фандинг в топ-5%» (хрупкость Ф3), не как вход.

---

## 3. Каталог 150 (уникальные, вечер 30.08.2026)

Колонка **нам** — одно слово. ★ округлены к живым на сегодня, где API ответил; иначе утренние.

### I. Движки и платформы (1–28)

| # | Репо | ★ | Что это | Нам |
|---|---|---|---|---|
| 1 | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 53843 | Свечной ритейл-бот | учить dry-run; не позвоночник |
| 2 | [ccxt/ccxt](https://github.com/ccxt/ccxt) | 43811 | Унифицированный API 100+ бирж | труба (не мозг) |
| 3 | [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 28153 | Event-driven ядро Rust+Py | **позвоночник** |
| 4 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 21417 | Институциональный движок | игнор как стек |
| 5 | [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | 19708 | MM/arb CEX+DEX | учить коннекторы |
| 6 | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | 8397 | Research-свечи, live платный | игнор |
| 7 | [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6494 | Grid/DCA/TV/LLM UI | антипример |
| 8 | [Superalgos/Superalgos](https://github.com/Superalgos/Superalgos) | 5632 | Визуальный конструктор | игнор |
| 9 | [Open-Trader/opentrader](https://github.com/Open-Trader/opentrader) | 2841 | Self-host GRID+DCA | антипример |
| 10 | [blankly-finance/blankly](https://github.com/blankly-finance/blankly) | 2468 | Build/backtest/deploy | игнор |
| 11 | [barter-rs/barter-rs](https://github.com/barter-rs/barter-rs) | 2245 | Rust event engine | смотреть рядом с Nautilus |
| 12 | [Lumiwealth/lumibot](https://github.com/Lumiwealth/lumibot) | 2013 | Агенты + брокеры, US-leaning | игнор |
| 13 | [c9s/bbgo](https://github.com/c9s/bbgo) | 1657 | Go; юзеры = grid2 | антипример стратегии |
| 14 | [rodrigo-brito/ninjabot](https://github.com/rodrigo-brito/ninjabot) | 1624 | Go бот/бэктест | игнор |
| 15 | [StockSharp/StockSharp](https://github.com/StockSharp/StockSharp) | 10667 | C# терминал | игнор |
| 16 | [edtechre/pybroker](https://github.com/edtechre/pybroker) | 3520 | Py бэктест | research |
| 17 | [thrasher-corp/gocryptotrader](https://github.com/thrasher-corp/gocryptotrader) | 3456 | Go биржевой клиент | труба |
| 18 | [gbeced/basana](https://github.com/gbeced/basana) | 861 | Async торговый фреймворк | игнор |
| 19 | [cassandre-tech/cassandre-trading-bot](https://github.com/cassandre-tech/cassandre-trading-bot) | 659 | Java Spring starter | игнор |
| 20 | [Quantweb3-com/NexusTrader](https://github.com/Quantweb3-com/NexusTrader) | 656 | «Pro» платформа, 3 issues | игнор |
| 21 | [richkuo/go-trader](https://github.com/richkuo/go-trader) | 344 | Go backtest/paper/live | смотреть риск-слой |
| 22 | [saniales/golang-crypto-trading-bot](https://github.com/saniales/golang-crypto-trading-bot) | 1163 | Консольный Go-бот | игнор |
| 23 | [gazbert/bxbot](https://github.com/gazbert/bxbot) | 862 | Java бот | игнор |
| 24 | [JulyIghor/QtBitcoinTrader](https://github.com/JulyIghor/QtBitcoinTrader) | 799 | Десктоп быстрых ордеров | игнор |
| 25 | [alexanderwanyoike/the0](https://github.com/alexanderwanyoike/the0) | 411 | Контейнерный рантайм стратегий | оркестратор |
| 26 | [mementum/backtrader](https://github.com/mementum/backtrader) | 23016 | Классика OHLC, issues off | не хост live |
| 27 | [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 8910 | Векторный бэктест | research |
| 28 | [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 8912 | Простой OHLC BT | research |

### II. Стратегии и боты, которые крутят (29–58)

| # | Репо | ★ | Класс | Нам |
|---|---|---|---|---|
| 29 | [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) | 3383 | Grind/DCA на FT | **антипример доливки** |
| 30 | [enarjord/passivbot](https://github.com/enarjord/passivbot) | 2085 | Грид перпов | **антипример грида** |
| 31 | [Haehnchen/crypto-trading-bot](https://github.com/Haehnchen/crypto-trading-bot) | 3516 | Dip-catch + TA | учить: BTC-фильтр просят и не меряют |
| 32 | [ctubio/Krypto-trading-bot](https://github.com/ctubio/Krypto-trading-bot) | 3709 | C++ MM | учить latency/cancel |
| 33 | [51bitquant/binance_grid_trader](https://github.com/51bitquant/binance_grid_trader) | 975 | Сетка спот+фьючи | антипример |
| 34 | [chrisleekr/binance-trading-bot](https://github.com/chrisleekr/binance-trading-bot) | 5548 | Дашборд+плагины | игнор края |
| 35 | [whittlem/pycryptobot](https://github.com/whittlem/pycryptobot) | 2057 | TA-бот | игнор |
| 36 | [asavinov/intelligent-trading-bot](https://github.com/asavinov/intelligent-trading-bot) | 1864 | ML-сигналы | игнор как вход |
| 37 | [TheFourGreatErrors/alpha-rptr](https://github.com/TheFourGreatErrors/alpha-rptr) | 691 | Мультибиржа фьючи | смотреть SL на бирже |
| 38 | [conor19w/Binance-Futures-Trading-Bot](https://github.com/conor19w/Binance-Futures-Trading-Bot) | 660 | TA USDT-M | игнор |
| 39 | [Erfaniaa/binance-futures-trading-bot](https://github.com/Erfaniaa/binance-futures-trading-bot) | 405 | Мультистратегия+TG | игнор |
| 40 | [cunarist/solie](https://github.com/cunarist/solie) | 59 | GUI Binance futures | мелкая практика |
| 41 | [Mtemi/Bybit-Trading-Bot-Integrated-with-TradingView-Webhook-Alerts](https://github.com/Mtemi/Bybit-Trading-Bot-Integrated-with-TradingView-Webhook-Alerts) | 518 | TV → Bybit | антипример (ТВ жмёт кнопку) |
| 42 | [kuegi/kuegiBot](https://github.com/kuegi/kuegiBot) | 120 | Личная дисциплина | мотив, не код |
| 43 | [Adamant-im/adamant-tradebot](https://github.com/Adamant-im/adamant-tradebot) | 848 | Сетка в мессенджере | антипример |
| 44 | [fabston/TradingView-Webhook-Bot](https://github.com/fabston/TradingView-Webhook-Bot) | 1849 | Алерт→ордер | инфра, не мозг |
| 45 | [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) | 5419 | Официальные сэмплы | «crap profits» |
| 46 | [freqtrade/frequi](https://github.com/freqtrade/frequi) | 1059 | UI FT | хост |
| 47 | [freqtrade/technical](https://github.com/freqtrade/technical) | 1031 | Индикаторы FT | мешок TA |
| 48 | [hummingbot/hummingbot-api](https://github.com/hummingbot/hummingbot-api) | 140 | Оркестрация ботов | хост |
| 49 | [hummingbot/gateway](https://github.com/hummingbot/gateway) | 255 | DEX middleware | не CEX-стол |
| 50 | [JohnKearney1/PassivBot-Configurations](https://github.com/JohnKearney1/PassivBot-Configurations) | 124 | Конфиги грида | антипример экосистемы |
| 51 | [princeniu/AS-Grid](https://github.com/princeniu/AS-Grid) | 40 | Мультибиржа грид | антипример |
| 52 | [ryu878/bybit_scalp_bot_v2](https://github.com/ryu878/bybit_scalp_bot_v2) | 92 | Скальп; MA с Binance как фильтр | ближайший **чужой** кросс-биржевой фильтр |
| 53 | [tiansin/docker_grid_trader](https://github.com/tiansin/docker_grid_trader) | 110 | Сетка Binance | антипример |
| 54 | [Hephyrius/binance_futures_bot](https://github.com/Hephyrius/binance_futures_bot) | 302 | USDT-M, мёртв 2022 | труп |
| 55 | [CryptoGnome/Bybit-Futures-Bot](https://github.com/CryptoGnome/Bybit-Futures-Bot) | 120 | Liquidation hunt | токсично |
| 56 | [yasinkuyu/binance-trader](https://github.com/yasinkuyu/binance-trader) | 2748 | Зомби, 0 issues | звёзды≠использование |
| 57 | [Rikj000/MoniGoMani](https://github.com/Rikj000/MoniGoMani) | 1026 | FT hyperopt-пак, archived | кладбище подгонки |
| 58 | [OctopusTakopi/funding-rate-alpha](https://github.com/OctopusTakopi/funding-rate-alpha) | 39 | Research фандинга | **единственный [S] край**; нам — вето/скринер |

### III. LLM / «команда аналитиков» (59–82)

| # | Репо | ★ | Суть | Нам |
|---|---|---|---|---|
| 59 | [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 101873 | Дебаты без ордера | контур B максимум; не A |
| 60 | [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 63099 | Персоны, paper | игнор |
| 61 | [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | 72508 | Дата, не бот | труба данных (опц.) |
| 62 | [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | 31476 | Форк A-shares | игнор |
| 63 | [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | 21840 | Арена агентов | игнор |
| 64 | [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 21191 | FinLLM | не кнопка |
| 65 | [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16149 | DRL бенчмарки | бумага |
| 66 | [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 7890 | Агент-платформа | бумага |
| 67 | [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 14366 | R&D агент | не стол |
| 68 | [NoFxAiOS/nofx](https://github.com/NoFxAiOS/nofx) | 12786 | LLM+кламп, ключи текли | кламп учить; ключи — антипример |
| 69 | [OpenByteInc/QuantDinger](https://github.com/OpenByteInc/QuantDinger) | 11209 | «Платформа» | `[M]` |
| 70 | [ValueCell-ai/valuecell](https://github.com/ValueCell-ai/valuecell) | 11007 | Десктоп агенты + биржи | карантин обязателен |
| 71 | [TradeMaster-NTU/TradeMaster](https://github.com/TradeMaster-NTU/TradeMaster) | 3054 | Academic RL | бумага |
| 72 | [wquguru/nof0](https://github.com/wquguru/nof0) | 2749 | Клон арены | игнор |
| 73 | [pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading) | 952 | Память+характер | идея журнала, не вход |
| 74 | [YoungCan-Wang/WyckoffTradingAgent](https://github.com/YoungCan-Wang/WyckoffTradingAgent) | 590 | Скринер | нет книги |
| 75 | [EthanAlgoX/LLM-TradeBot](https://github.com/EthanAlgoX/LLM-TradeBot) | 315 | Агенты+Binance | антипример контура A |
| 76 | [51bitquant/ai-hedge-fund-crypto](https://github.com/51bitquant/ai-hedge-fund-crypto) | 619 | Крипто-форк персон | игнор |
| 77 | [KylinMountain/TradingAgents-AShare](https://github.com/KylinMountain/TradingAgents-AShare) | 804 | Ещё форк | игнор |
| 78 | [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) | 3114 | Ещё форк | игнор |
| 79 | [charliedream1/ai_quant_trade](https://github.com/charliedream1/ai_quant_trade) | 6429 | Свалка AI-квант | шум |
| 80 | [ma-pony/cryptotrader-ai](https://github.com/ma-pony/cryptotrader-ai) | 12 | 4 агента, 0 людей в issues | идея rule-gates |
| 81 | [LLMQuant/awesome-trading-agents](https://github.com/LLMQuant/awesome-trading-agents) | 436 | Каталог агентов | карта шума |
| 82 | [blitzcrieg1/sentinel-trader-research](https://github.com/blitzcrieg1/sentinel-trader-research) | 0 | Честный минус LLM | `[S]` отрицательный |

### IV. Зоны, профиль, SMC, стакан (83–118)

| # | Репо | ★ | Суть | Нам |
|---|---|---|---|---|
| 83 | [joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) | 1966 | SMC-либа, lookahead #101 | **не истина** |
| 84 | [bfolkens/py-market-profile](https://github.com/bfolkens/py-market-profile) | 404 | POC/VAH/VAL | гипотеза зоны |
| 85 | [srlcarlg/srl-python-indicators](https://github.com/srlcarlg/srl-python-indicators) | 50 | OF ticks, VP, Weis | графики |
| 86 | [keithorange/PatternPy](https://github.com/keithorange/PatternPy) | 475 | Паттерны, «garbage» | игнор |
| 87 | [stockalgo/stolgo](https://github.com/stockalgo/stolgo) | 347 | Price-action API | мало практики |
| 88 | [Elenchev/order-book-heatmap](https://github.com/Elenchev/order-book-heatmap) | 510 | Теплокарта L2 | viz |
| 89 | [murtazayusuf/OrderflowChart](https://github.com/murtazayusuf/OrderflowChart) | 249 | Footprint, archived | viz |
| 90 | [tysonwu/stack-orderflow](https://github.com/tysonwu/stack-orderflow) | 138 | Footprint GUI | viz |
| 91 | [AndreaFerrante/Orderflow](https://github.com/AndreaFerrante/Orderflow) | 137 | Пакет reshape | либа |
| 92 | [Crypto-toolbox/HFT-Orderbook](https://github.com/Crypto-toolbox/HFT-Orderbook) | 1384 | Структура книги | кирпич |
| 93 | [zcakhaa/Deep-Convolutional-Neural-Networks-for-Limit-Order-Books](https://github.com/zcakhaa/Deep-Convolutional-Neural-Networks-for-Limit-Order-Books) | 606 | DeepLOB | бумага, утечка |
| 94 | [sadighian/crypto-rl](https://github.com/sadighian/crypto-rl) | 966 | LOB+RL | мёртвый toolkit |
| 95 | [alpacahq/example-hftish](https://github.com/alpacahq/example-hftish) | 868 | OBI акции | не крипта |
| 96 | [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | 4565 | Реплей HFT | **труба реплея** |
| 97 | [nkaz001/algotrading-example](https://github.com/nkaz001/algotrading-example) | 323 | OBI бэктесты | research |
| 98 | [mdibo/Avellaneda-Stoikov](https://github.com/mdibo/Avellaneda-Stoikov) | 155 | AS MM | не отскок |
| 99 | [ragoragino/avellaneda-stoikov](https://github.com/ragoragino/avellaneda-stoikov) | 94 | То же | бумага |
| 100 | [tardis-dev/tardis-python](https://github.com/tardis-dev/tardis-python) | 147 | История тиков/L2 | **труба** |
| 101 | [tardis-dev/tardis-node](https://github.com/tardis-dev/tardis-node) | 366 | То же Node | труба |
| 102 | [tardis-dev/tardis-machine](https://github.com/tardis-dev/tardis-machine) | 310 | Локальный реплей | труба |
| 103 | [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed) | 2890 | Нормализация WS | **труба рекордера** |
| 104 | [oliver-zehentleitner/unicorn-binance-websocket-api](https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api) | 736 | Binance WS | труба |
| 105 | [oliver-zehentleitner/unicorn-binance-local-depth-cache](https://github.com/oliver-zehentleitner/unicorn-binance-local-depth-cache) | 52 | Локальный L2 кэш | учить ресинк |
| 106 | [crypto-chassis/ccapi](https://github.com/crypto-chassis/ccapi) | 732 | C++ биржи | труба |
| 107 | [sammchardy/python-binance](https://github.com/sammchardy/python-binance) | 7207 | SDK, 500+ issues | поломки Binance |
| 108 | [bybit-exchange/pybit](https://github.com/bybit-exchange/pybit) | 670 | Официальный Bybit SDK | **наша биржа** |
| 109 | [hyperliquid-dex/hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) | 1810 | HL SDK | киты Ф3 |
| 110 | [microsoft/MarS](https://github.com/microsoft/MarS) | 1777 | Генеративный рынок | research |
| 111 | [FinancialComputingUCL/LOBFrame](https://github.com/FinancialComputingUCL/LOBFrame) | 255 | Обработка LOB | research |
| 112 | [LeonardoBerti00/TLOB](https://github.com/LeonardoBerti00/TLOB) | 170 | Transformer LOB | бумага |
| 113 | [KVignesh122/MT5-SMC-trading-bot](https://github.com/KVignesh122/MT5-SMC-trading-bot) | 75 | MT5 OB/FVG | не крипто-перп |
| 114 | [Prasad1612/smart-money-concept](https://github.com/Prasad1612/smart-money-concept) | 42 | Ещё SMC-порт | игрушка |
| 115 | [KenjiLoo/volume-profile-bot](https://github.com/KenjiLoo/volume-profile-bot) | 1 | Единственный VP-фьюч бот | пусто, 0 issues |
| 116 | [andrewlfc7/BFX-BSI](https://github.com/andrewlfc7/BFX-BSI) | 22 | Bitfinex orderflow-бот | личный, 0 issues |
| 117 | [tapedelta/kline-orderbook-chart](https://github.com/tapedelta/kline-orderbook-chart) | 31 | Heatmap+liq heatmap | viz, не магнит входа |
| 118 | [dyn4mik3/OrderBook](https://github.com/dyn4mik3/OrderBook) | 411 | Матчинг LOB | кирпич |

### V. Пары, BTC-фильтр, киты, копи (119–130)

| # | Репо | ★ | Суть | Нам |
|---|---|---|---|---|
| 119 | [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | 4915 | López de Prado toolkit | учить CPCV, не крипта |
| 120 | [hudson-and-thames/arbitragelab](https://github.com/hudson-and-thames/arbitragelab) | 689 | Пары/OU | не альт-вето |
| 121 | [lamres/pairs_trading_cryptocurrencies_strategy_catalyst](https://github.com/lamres/pairs_trading_cryptocurrencies_strategy_catalyst) | 49 | Пары на мёртвом Catalyst | труп |
| 122 | [farhanarshad00/Statistical-Arbitrage_Crypto](https://github.com/farhanarshad00/Statistical-Arbitrage_Crypto) | 0 | README: «BTC market filter» | идея есть, кода-закона нет |
| 123 | [djienne/COPY_WALLET_HYPERLIQUID](https://github.com/djienne/COPY_WALLET_HYPERLIQUID) | 30 | Копи кошелька HL | **запрет копи** |
| 124 | [severin-richner/binance-futures-top-traders-bot](https://github.com/severin-richner/binance-futures-top-traders-bot) | 30 | L/S ratio топов | лаг, archived |
| 125 | [unhappyben/HyperliquidPositionsBot](https://github.com/unhappyben/HyperliquidPositionsBot) | 2 | Трекер позиций в Discord | сырьё китов, не вход |
| 126 | [BowTiedDevil/degenbot](https://github.com/BowTiedDevil/degenbot) | 562 | DEX arb | не CEX-стол |

### VI. Инфра, списки, образование (131–142)

| # | Репо | ★ | Суть | Нам |
|---|---|---|---|---|
| 127 | [wilsonfreitas/awesome-quant](https://github.com/wilsonfreitas/awesome-quant) | 29319 | Каталог квант | карта |
| 128 | [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | 20724 | Книга | учёба |
| 129 | [je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading) | 10653 | Тетрадки | учёба |
| 130 | [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | 14068 | Каталог | карта |
| 131 | [botcrypto-io/awesome-crypto-trading-bots](https://github.com/botcrypto-io/awesome-crypto-trading-bots) | 2496 | Каталог ботов | карта; не проверяют код |
| 132 | [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) | 12218 | TA wrapper | индикаторы ≠ зона |
| 133 | [bukosabino/ta](https://github.com/bukosabino/ta) | 5181 | Pandas TA | то же |
| 134 | [matplotlib/mplfinance](https://github.com/matplotlib/mplfinance) | 4427 | Свечи | viz |
| 135 | [highfestiva/finplot](https://github.com/highfestiva/finplot) | 1181 | Быстрые графики | viz |
| 136 | [mhallsmoore/qstrader](https://github.com/mhallsmoore/qstrader) | 3449 | Equity BT | игнор |
| 137 | [jesse-ai/example-strategies](https://github.com/jesse-ai/example-strategies) | 177 | Примеры EMA/RSI | не стол |
| 138 | [ivopetiz/algotrading](https://github.com/ivopetiz/algotrading) | 1668 | Свалка скриптов | шум |
| 139 | [hackingthemarkets/binance-tutorials](https://github.com/hackingthemarkets/binance-tutorials) | 1034 | Туториалы | учёба |
| 140 | [Roibal/Cryptocurrency-Trading-Bots-Python-Beginner-Advance](https://github.com/Roibal/Cryptocurrency-Trading-Bots-Python-Beginner-Advance) | 1441 | Учебные боты | учёба |
| 141 | [CryptoSignal/Crypto-Signal](https://github.com/CryptoSignal/Crypto-Signal) | 5623 | Сигнальный спам | игнор |
| 142 | [databento/databento-python](https://github.com/databento/databento-python) | 296 | Платные L3 | не путь к 900k |

### VII. Мёртвые, скам, шум — чтобы фильтр был честным (143–150)

| # | Репо | ★ | Почему в списке |
|---|---|---|---|
| 143 | [askmike/gekko](https://github.com/askmike/gekko) | 10186 | Archived 2020. Когда-то дефолт Node. Стратегии проигрывали B&H |
| 144 | [DeviaVir/zenbot](https://github.com/DeviaVir/zenbot) | 8260 | Archived, 290 leftover issues |
| 145 | [scrtlabs/catalyst](https://github.com/scrtlabs/catalyst) | 2560 | Мёртвый crypto-Zipline; убил пары в п.121 |
| 146 | [michaelgrosner/tribeca](https://github.com/michaelgrosner/tribeca) | 4117 | Старый MM, 2021 |
| 147 | [warp-id/solana-trading-bot](https://github.com/warp-id/solana-trading-bot) | 2330 | Солана-снайпер класс |
| 148 | [mortdeus/solana-copy-sniper-mev-trading-bot](https://github.com/mortdeus/solana-copy-sniper-mev-trading-bot) | 4441 | Keyword-stuffed MEV |
| 149 | [yeahrb/CEX-Option-Futures-Crypto-Quant-Algorithm-Trading-Bot](https://github.com/yeahrb/CEX-Option-Futures-Crypto-Quant-Algorithm-Trading-Bot) | 486 | Telegram в описании `[M]` |
| 150 | [0xzkleo/polymarket-5min-crypto-trading-bot](https://github.com/0xzkleo/polymarket-5min-crypto-trading-bot) | 136 | Спам-описание; не наш рынок |

*(Утро + вечер без двойного счёта движков ≈ 150 строк выше. Соседние имена из поисков — клоны Bybit с 0–8★, Cortex-AI «#1 bot 2026», deepalpha «84.9% accuracy» — в каталог не включались как мусор; смысл тот же, что п.149.)*

---

## 4. Сводка по классам

| Класс | Сколько в 150 | С чужими операционными issues | Что крутят | Стол занят? |
|---|---|---|---|---|
| Движки | 28 | Freqtrade, Nautilus, Hummingbot, OctoBot, bbgo, Lean | Платформа | Ядро — да (Nautilus). Стратегия стола — нет |
| Грид/DCA/grind | ~15 явных + UI | NFI, passivbot, OctoBot, 51bitquant, bbgo grid2 | **Да, живые деньги** | Занято тем, что нам **запрещено** |
| Свечной TA / dip | ~15 | Haehnchen, alpha-rptr, pycryptobot | Частично | Не зона+жест |
| LLM-команды | 24 | nofx (ключи), остальное paper | Ордера почти нет | Занято театром, не столом |
| SMC/ICT/VP | 12 | 1 либа (lookahead) | TradingView/MT5 золото | Крипто-перп бота нет |
| Стакан / footprint | 20 | визуализаторы, Tardis/cryptofeed | Данные да, вход нет | PRS/ZLG как продукт — **пусто** |
| BTC-вето | 2 намёка | Haehnchen #358, ryu878 MA | Нет закона | **Пусто** |
| Киты/копи | 4 | — | Копи = запрет | Фильтр когорты — пусто как продукт |
| Мёртвые/скам | 8 показательных | n/a | — | Фильтр |

---

## 5. Что брать / не брать в код

**Брать (инфра, не сигналы)**  
Nautilus — позвоночник. cryptofeed / Tardis / pybit / ccxt — трубы. hftbacktest — идеи реплея L2. unicorn depth-cache — ресинк. nofx — только идея «кламп в рантайме, не в промпте». Haehnchen #358 — мотив измерить BTC-вето. funding-rate-alpha — приор для хрупкости фандинга. mlfinlab — CPCV/эмбарго, когда дойдём до казни стратегии.

**Не брать (закон стола)**  
NFI grind, passivbot, OctoBot/OpenTrader GRID-DCA, любые `average_in`. SMC как сигнал (lookahead). TV-webhook как вход. Копи HL. LLM в hot path (TradingAgents-трейдер, nofx-ордер, LLM-TradeBot). Снайперы Solana/MEV. Ликвидационный хантинг. «84.9% accuracy» нейроботы.

**Не строить заново**  
Ещё один свечной бэктестер (vectorbt/backtesting.py/Jesse сэмплы). Ещё один footprint-GUI. Ещё один awesome-список.

---

## 6. Что изменилось с утренней переписи (~110)

1. Подтянуты живые ★: Nautilus **28.2k** (не «просто движок в списке» — второй по смыслу после Freqtrade для *нашего* выбора ядра). TradingAgents перешагнул **101k**. nofx **518** открытых issues — это уже операционка, не демо.  
2. Новый массовый UI-класс: **OpenTrader**, **chrisleekr** (5.5k) — тот же грид/дашборд, не стол.  
3. Каталог агентов (`awesome-trading-agents`) подтвердил: форки TradingAgents — отдельная индустрия A-shares. К крипто-перп столу не приблизились.  
4. Bybit-поиск: кроме Haehnchen/passivbot/pybit/ryu878 — кладбище 0–8★ и TV-webhook. **Нативного Bybit-стола зоны+стакан нет.**  
5. Поле «первые в исходах» вечером так же пусто, как утром.

---

## 7. Для следующего агента

Не начинать стратегию «как NFI, но умнее». Не импортировать `smart-money-concepts` в прод. Не ставить Freqtrade позвоночником. Первые коммиты кода по-прежнему: recorder + book bit-in-bit + запрет `average_in` (`PHASE-BUILD` −1.3 и 0.1.x).

Если звёзды в этой таблице разъедутся с API — править дату шапки, не вердикт. Вердикт меняется только если появится репо с **чужими** issues вида «наш жест DEFEND на SOL live разошёлся с тенью» — такого репо нет.

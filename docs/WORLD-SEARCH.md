# Мировой поиск: GitHub, Gitee и площадки стран

**Дата:** 30.08.2026, ночь.  
**Зачем:** две предыдущие переписи ([CENSUS-150.md](CENSUS-150.md), [FUTURES-BOTS-RESULTS.md](FUTURES-BOTS-RESULTS.md)) были в основном **английский GitHub**. Этот файл — тот же стол (зона, жест стакана, veto BTC, карточка, запрет усреднения, funding) на **других языках и площадках**.

**Итог одной строкой:** пустой продукт **не заполнен ни в Китае, ни в Индии, ни в Корее, ни в Японии, ни в Бразилии, ни на Gitee/GitLab**. Везде одни и те же религии под другими именами: сетка, DCA, 跟单, 缠论, ICT, «robô trader». **Zone × жест 8 с × наша таблица × тишина** как публичный живой атом по перпам — не найден.

Связано: [INVENTION-FIRST-FACT.md](INVENTION-FIRST-FACT.md), [SR-LEVELS-SCIENCE.md](SR-LEVELS-SCIENCE.md), [FORUMS-LEVELS-BOUNCE-BTC.md](FORUMS-LEVELS-BOUNCE-BTC.md).

---

## 1. Как искали (проверяемый срез, не «весь интернет»)

**Площадки**

| Площадка | Что это | Что нашли этой ночью |
|---|---|---|
| GitHub Search API + `gh repo view` | мировой код | именованные репы ниже; ★ на 30.08.2026 |
| Gitee / GitCode | китайский код | те же сетки и 缠论; зеркала VN.py |
| GitLab topic `crypto-trading` | второй хостинг | AI-пассивный доход, копи, снайпер Raydium. Пусто |
| TradingView публичный Pine | график | ICT, 缠论, footprint бара. Нет PRS биржи |
| 聚宽 / 米筐 / 掘金 / BigQuant / UQER / QMT | CN quant | A-share и CTP. Крипто-перп не центр |
| QuantConnect | US research | акции/CME, не Bybit жест |
| Elite Trader, Reddit, Bitcointalk | EN форумы | фольклор отскока (уже в FORUMS-*) |
| 雪球, 东方财富, 掘金社区 | CN соц | CTA, сетки, 跟单 |
| 52pojie | CN warez | взломанные EA — **не продукт** |
| Zerodha Streak / Tradetron / AlgoTest | Индия | NSE акции/опционы, не крипто-перпы |
| 3Commas, Bitsgap, Pionex, WunderTrading | коммерция | GRID/DCA/copy — [FUTURES-BOTS-RESULTS](FUTURES-BOTS-RESULTS.md) |
| Hyperliquid leaderboard | живые деньги | люди, не скачиваемый бот |

**Языки запросов (смысл один)**

| Язык | Зона | Стакан | Сетка / усреднение | Боты |
|---|---|---|---|---|
| EN | support resistance, FVG, ICT | order book, VSA, footprint | grid, DCA, martingale | crypto futures bot |
| ZH | 支撑阻力, 缠论, 中枢 | 订单簿, 盘口, 资金费率 | 网格, 加仓, 马丁 | 合约量化 |
| JA | 支持線 抵抗線 | 板 | グリッド, ナンピン | 仮想通貨 自動売買 |
| KO | 지지 저항 | 호가창 | 그리드, 물타기 | 코인 자동매매 선물 |
| HI | सपोर्ट रेजिस्टेंस | ऑर्डर बुक | ग्रिड | क्रिप्टो बॉट |
| PT | suporte resistência | book, fluxo | grade, martingale | robô trader futuros |
| ES | soporte resistencia | libro de órdenes | rejilla | bot futuros cripto |
| RU | уровни, отскок | стакан, VSA | сетка, усреднение | бот фьючерсы |
| TR | destek direnç | emir defteri | ortalama | kripto bot vadeli |
| VI | hỗ trợ kháng cự | sổ lệnh | lưới | bot futures |
| ID / AR / DE / FR | те же корни | orderbuch / carnet | grid / شبكة | bot / بوت |

Нативные запросы PT/ES/TR/VI/HI/AR на GitHub этой ночью дали **0 реп** с живой экосистемой. Розница этих стран **потребляет** английские и китайские сетки, а не пишет свой атом.

---

## 2. Китай — самый важный «другой» мир

### 2.1 Инфра (брать как проводку, не как сигнал)

| Репо | ★ 30.08 | Что это | Нам |
|---|---|---|---|
| [vnpy/vnpy](https://github.com/vnpy/vnpy) (зеркало [Gitee](https://gitee.com/vnpy/vnpy)) | **44 979** | Китайский Nautilus: CTP, шлюзы, движок | Как CN-стол подключает биржи. **Не позвоночник** (у нас Nautilus) |
| [veighna-global/vnpy_evo](https://github.com/veighna-global/vnpy_evo) | 380 | Крипто-форк: Binance / OKX / **Bybit**. Официальный VN.py крипту снял из-за регулятора КНР ([issue #3536](https://github.com/vnpy/vnpy/issues/3536)) | Шлюз Bybit как референс. Стратегии Nova — не наш атом |
| [51bitquant/howtrader](https://github.com/51bitquant/howtrader) | 949 | Форк VN.py + **TradingView webhook** + сетки | Антипример входа «алерт → ордер» |
| [51bitquant/bitquant](https://github.com/51bitquant/bitquant) | 1 153 | Курс: CCXT, сетка, **мартингейл** | Учить как «что гоняет CN-ритейл» |

Полигоны исследований (聚宽, 米筐, 掘金, BigQuant, UQER, PTrade, QMT): центр — **A-share и товарные фьючерсы**. Полигон 2024–26: JoinQuant без нативного крипто-реала (симулятор). Это не Bybit L2.

### 2.2 Местная религия вместо ICT: 缠论 (Chanlun)

Автор: 缠中说禅. Геометрия: 分型 → 笔 → 线段 → 中枢 → 买卖点. Смотрит **уже нарисованную свечу**, не четыре ведра нового размера за 8 с.

| Репо | ★ | Замечание |
|---|---|---|
| [waditu/czsc](https://github.com/waditu/czsc) | **5 946** | Самая живая реализация (Rust+Python). Акции и CTP-фьючерсы. 220+ «сигналов» по свечам |
| [Vespa314/chan.py](https://github.com/Vespa314/chan.py) | 2 047 | Открытый фреймворк, много ТФ, визуализация |
| [yijixiuxin/chanlun-pro](https://github.com/yijixiuxin/chanlun-pro) + Gitee `quant_trade/chanlun-pro` | 979 | Есть экран «цифровая валюта» и VN.py. Лицензия **pyarmor**: 20 дней по WeChat. Геометрия + замок |
| [haigechanlun/chanlun_auto_trading](https://github.com/haigechanlun/chanlun_auto_trading) | 131 | «Годовая 80%+» в README; ядро **не открыто**; открытое — MACD+TD с **динамическим доливом** |
| [yuebuluo168/chan-trader](https://github.com/yuebuluo168/chan-trader) | 0 | Свечи 1h/4h/1d → BUY. Нет стакана |
| [164149043/chanlun](https://github.com/164149043/chanlun) | мало | Свечи + **LLM** (DeepSeek/GPT) как оракул. Запрещённый контур A |

**Это не ZLG.** Документируем как китайский ICT: популярно, lookahead/ручная разметка типичны, в контур A не импортировать.

### 2.3 Коммерция и Gitee: сетка + 补仓 + 跟单

| Репо / продукт | ★ / где | Суть | Закон стола |
|---|---|---|---|
| [hengxuZ/binance-quantization](https://github.com/hengxuZ/binance-quantization) и зеркала Gitee (`XingFuCunDeMaNong`) | **1 330** | `double_throw_ratio` = докупить ниже. «Пакет научим» | **Запрещено** (усреднение) |
| [51bitquant/binance_grid_trader](https://github.com/51bitquant/binance_grid_trader) | 975 | Сетка спот + USDT-перп Binance; README на PT | Запрещено |
| [51bitquant/multi_pairs_martingle_bot](https://github.com/51bitquant/multi_pairs_martingle_bot) | 126 | Прямо в имени | Запрещено |
| Gitee `bothway-grid`, `contract-two-way-grid-trends` | зеркала | Двусторонняя сетка + «собираем падение» | Запрещено |
| [QuantiaAI/grid-pilot](https://github.com/QuantiaAI/grid-pilot) | 212 | «Динамическая сетка», 12 языков UI | Запрещено |
| [cryptocj520/grid](https://github.com/cryptocj520/grid) | живой | Три режима, один из них **马丁网格** | Запрещено |
| 合约跟单 (Binance/OKX/Bybit copy) | коммерция | Чужой вход | Запрещено |

Публичного «проверенный WR по перпам с журналом жестов» в CN нет. 52pojie — взломанные советники, не стол.

**Вывод CN:** лучшая инфра (VN.py / Evo) — да. Пустой продукт — всё ещё пуст.

---

## 3. США / английский мир

Уже в CENSUS-150 и FUTURES-BOTS-RESULTS. Коротко, чтобы не разъехаться:

- Звёздный театр: TradingAgents (~102k★), OpenBB, Freqtrade, Nautilus.
- Живые деньги OSS = сетки и DCA (NFI, passivbot, OctoBot).
- Единственный посчитанный край в 150 = `funding-rate-alpha`.
- Честный проигрыш = Hummingbot/Midas.
- Haehnchen BTC-фильтр на альтах — годами просят ([#358](https://github.com/Haehnchen/crypto-trading-bot/issues/358)), не измерен.
- ICT/SMC/VSA/Bookmap — религии графика. TradingView с 01.03.2026 даёт `request.footprint()` — это **объём внутри бара**, не 8 с стакана биржи.

Новых EN-находок, которые закрывают атом, нет.

---

## 4. Индия

Продуктовый центр — **NSE**, не крипто-перпы.

| Площадка | Что делает | К крипто-столу |
|---|---|---|
| Zerodha **Streak** | условие на бумаге → ордер у брокера | Алерт → ордер. Нет стакана |
| **Tradetron** | мультиброкер, маркетплейс стратегий | То же. Bybit нативно не центр |
| **AlgoTest / Sensibull / Opstra** | опционы NSE | Другой рынок |
| AstraBit / Traydar / TV-Hub | мост TradingView → Bybit | Запрещённый класс webhook |

Хинди-контент: сигналы и Telegram сильнее GitHub. Поиск `crypto trading bot india` не дал отдельной школы зоны×жеста. GitHub IN = форки Freqtrade и pybit, 0★-кладбище, тот же состав, что EN.

---

## 5. Япония

Запрос `仮想通貨 自動売買` на GitHub: **0–5★** игрушки под bitFlyer (`haruocode/simpleTrader` 5★ и хвост 0–1★). Нет второй экосистемы.

Розница: сетка/DCA на GMO Coin, bitFlyer, Coincheck. Бытовое слово **ナンピン** = усреднение вниз. Академический HFT — акции Токио, не публичный Bybit-жест.

---

## 6. Корея

Запрос `코인 자동매매`: **0–4★**, почти всё **Upbit спот** (`jiminAn/Coin_Auto_Trading` 4★, `mojitozoo20/Upbit-Coin-Auto-Trading` 3★). Перпы у розницы — на зарубежных биржах, код берут английский/китайский (passivbot, 3Commas).

Корейские гайды 2026 (알고랩 и блоги Bybit API) учат: Python + pybit + сетка/хедж фандинга + TV webhook. **물타기** = усреднение, быт, не наука. Незарегистрированные автосервисы — мишень регулятора. Публичного ZLG нет.

`sinmb79/straregy-consol` — Binance futures + картинка в LLM. Контур A запрещён.

---

## 7. Бразилия, испаноязычный мир, прочие языки

- **PT:** отдельной звезды «robô trader» нет. Китайский `binance_grid_trader` завёл `README-Portuguese.md` — розница читает CN-сетку по-португальски.
- **ES / LATAM:** «bot futuros cripto» = 3Commas / Bitsgap / Telegram. ProfitChart / Nelogica — B3, не Bybit L2.
- **TR / VI / ID / TH / AR / DE / FR:** нативные запросы на GitHub — пусто или общемировые OctoBot/passivbot. Слова lưới / شبكة / Grid / grille — один продукт.
- GitLab topic `crypto-trading`: «AI passive income», Bitget TA+LLM (`buft`), социальный копи NVSTly, снайпер Raydium. **Не стол.**

---

## 8. Россия и СНГ

Форумы уже разобраны в [FORUMS-LEVELS-BOUNCE-BTC.md](FORUMS-LEVELS-BOUNCE-BTC.md). Дополнение этой ночи:

| Репо | Что рекламирует | Нам |
|---|---|---|
| [poliakarmai/bybit-ws](https://github.com/poliakarmai/bybit-ws) | «Bollinger Grid + AI, LSTM 82.3%, Entry Judge DeepSeek, DCA» | Театр + сетка + доливка + LLM в входе |
| [Cikle/bybit-dca-trading-bot](https://github.com/Cikle/bybit-dca-trading-bot) | Leveraged grid + DCA | Запрещено |
| [posokhin/bybit-spot-trading-bot](https://github.com/posokhin/bybit-spot-trading-bot) | NonLinearDCA | Запрещено (спот, но идея та же) |

Смарт-лаб и Telegram по-прежнему описывают отскок руками. Журнала жестов нет.

---

## 9. Ключевые моменты стола — есть ли они где-то ещё

| Момент нашего стола | Где искали | Что есть в мире | Вывод |
|---|---|---|---|
| Преднарисованная зона S/R | 支撑阻力, support, destek, hỗ trợ | S/R, фибо, ICT FVG, 缠论 中枢, VWAP | Геометрия везде. **Жест в зоне — нет** |
| Отскок vs пробой | bounce/break, 反弹/突破 | Фольклор + TV | Нет развилки 2+2 с карточкой |
| Жест стакана 8 с (ZLG) | 盘口, 호가창, footprint, VSA | Bookmap, Sierra, TV `request.footprint()` | Картинка / бар. **Не 4 ведра × исход** |
| PRS | replenishment, 回补 | Академия HFT акций | Не розничный крипто-бот |
| Veto BTC на альтах | BTC filter alt | Haehnchen #358; нет CN/IN цифры | Берём как закон |
| Карточка новости | 财经日历, CPI, FOMC | Календари везде; LLM-сентимент | Карточка — наша. Сентимент = градусник |
| Авторы 3–13% | KOL, 意见领袖 | Лайки, не попадания в *наш* журнал | Роль 4 режет |
| Запрет усреднения | 马丁, ナンピン, 물타기, martingale | Везде **рекомендуют** | Наш запрет против мирового быта |
| Funding как фильтр | 资金费率 | Единственный посчитанный OSS-край | F3: хрупкость, не вход |
| Сетка / DCA | 网格, grid, lưới | Мировой розничный стандарт | Запрещено |
| LLM в контуре A | TradingAgents, chanlun+GPT, bybit-ws | Театр + ключи | Запрещено |
| «Первые по PnL» | 最强机器人, best bot | WSOT +37% — Saxo, не крипто. HL — люди | Первый = журнал исходов |

---

## 10. Ближайшие «двоюродные» методы (не клоны)

| Метод | Где живёт | На что смотрит | Чем не ZLG |
|---|---|---|---|
| ICT / SMC | EN YouTube, TV | FVG, OB, ликвидность свечи | Геометрия после факта |
| 缠论 Chanlun | CN GitHub/Gitee | Пивоты, отрезки, 中枢 | Свечи, не 8 с стакана |
| VSA / Wyckoff | EN/RU школы | Спред свечи × объём | Бар, не 100 мс |
| Footprint / Bookmap / TV footprint | US/EU деск, Premium TV | Кластеры дельты на баре | Глаз, не 4 ведра |
| VWAP desk | US акции | Отклонение от VWAP | Другой рынок |
| DOM tape | CME | Лента глазами | Нет таблицы + тишины |
| CTA / 趋势跟踪 | CN платформы | Пробой канала | Не зона отскока |

**Пустой атом по-прежнему один, теперь шире:**  
преднарисованная зона × свечной аккорд × жест 8 с × согласие жюри (не среднее) × частота *наших* классов × молчание, пока n мал.  
Жюри и %/час: [`INVENTION-JURY.md`](INVENTION-JURY.md). ICT/缠论 — только свеча. Сетки — без свечи как голоса. Склеенного автомата нет.

---

## 11. Что брать / не брать после мирового поиска

**Брать (инфра и фильтры, не сигнал)**

- VN.py / vnpy_evo — как китайский пример шлюзов (рядом с Nautilus, **не вместо**).
- Календари CPI/FOMC/NFP — уже в PHASE-BUILD.
- Funding как фильтр хрупкости (F3), не как вход.
- Академический PRS — наблюдать, не торговать.
- Haehnchen #358 — мотив измерить BTC-вето, не клон кода.

**Не брать ни на каком языке**

- 网格 / grid / 그리드 / lưới / rejilla / ナンピン-сетка.
- 马丁 / ナンピン / 물타기 / martingale / DCA / `double_throw` / «снизить цену входа».
- 合约跟单 / copy / HL-копии / сигнал из Telegram.
- 缠论 / ICT / SMC **как вход** в контур A.
- pyarmor-замки, 52pojie, «holy grail» SourceForge.
- Streak / Tradetron / howtrader-TV «алерт → ордер».
- LLM в контуре A (TradingAgents, chanlun+GPT, bybit-ws Entry Judge).

---

## 12. Остаточный риск этого поиска

- Закрытые проп-дески (CN CTA, US HFT, KR) **не публикуют** код. Мы не утверждаем, что «никто в мире так не думает». Мы утверждаем: **публичного живого атома нашего типа нет** — клонировать нечего.
- Китайские закрытые фонды на CTP не есть Bybit-перп стол.
- Завтра может выйти репа. Пустота проверяется **нашей** таблицей, не звёздами.

---

## 13. Что это меняет в плане

Ничего в деньгах, фазах и запретах.

Меняет только уверенность: пустой продукт — **мировой**, не англоязычный. Первый в мире по-прежнему = журнал исходов после ~100 *наших* жестов ([FIRST-IN-WORLD.md](FIRST-IN-WORLD.md)), не PnL и не «обогнали Китай».

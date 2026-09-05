# Поиск на GitHub: индикатор «как Nexus», топ 2026

**Тип:** аналитика. Код системы не менялся.  
**Дата среза:** 2026-09-05.  
**Запрос:** найти на GitHub такой индикатор, как в `docs/TV-STANDALONE-INDICATOR.md` (один overlay Pine v6: карта + футпринт + сессии + SMC/FVG + счёт входа/выхода), среди самых заметных проектов 2026.

---

## 1. Ответ одной фразой

**Такого репозитория в топе GitHub нет.**  
Самый используемый в мире аналог по *геометрии* SMC — не GitHub, а открытый скрипт TradingView **Smart Money Concepts [LuxAlgo]** (~4.8 млн «Add to chart», ~164 тыс. бустов на 2026-09-05).  
Самый близкий *открытый* «всё в одном» SMC/ICT на GitHub — **Synvoya/Confluence** (15 модулей, 1 звезда).  
Самый близкий *по архитектуре счёта + `request.footprint()`* — **chris-c-thomas/chrd-tradingview-pine-scripts** (12 звёзд, скальпер SPY 0DTE, не SMC-сюит).  
Ни один из них не закрывает все 22 пункта и не даёт честный вход/выход на футпринте бара плюс карте.

---

## 2. Как искали

Публичный GitHub Search API (без авторизации), веб-страницы репозиториев и карточки TradingView. Запросы:

- `smart money concepts pinescript`, `FVG order block`, `ICT pinescript`, `confluence SMC`
- `volume profile pinescript`, `CVD pinescript`, `order flow pinescript`, `volume delta pine`
- `request.footprint`, `tradingview footprint pine`
- точечная выгрузка известных имён: LuxAlgo, Synvoya, Quant-Edge, TradingAgents, Robwhitlow, TauricResearch

Кодовый поиск `request.footprint language:Pine` через API недоступен (401). Следы вызова найдены вручную: справочник Pine v6 и один рабочий продукт (SPY scalper выше).

**Важно про «топ GitHub».** Звёзды в теме Pine почти не измеряют качество SMC-индикатора. Репозитории на 400–1800 звёзд — это *списки*, *транспиляторы* и *старые коллекции осцилляторов*, не продукт из 22 пунктов. Реальная популярность живёт на TradingView (бусты / Add to chart).

---

## 3. Два рейтинга, которые нельзя смешивать

| Мир | Что считают «топом» | Чем это не является |
|---|---|---|
| GitHub stars | инфраструктура Pine, LLM-агенты, awesome-листы | готовый закрытый индикатор входа/выхода |
| TradingView usage | LuxAlgo SMC, платные PAC / OrderFlow IQ, клоны 2026 | исходник на GitHub и честный футпринт |

### 3.1. GitHub: что реально «топ» рядом со словом Pine (сентябрь 2026)

| ★ | Репозиторий | Что это | Отношение к Nexus |
|---|---|---|---|
| 102 518 | [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | Python, мультиагентный LLM-фреймворк | Не Pine. Не график. Не L2. Пункт 21 в ТЗ — *роли*, не эта сетка |
| 1 862 | [pAulseperformance/awesome-pinescript](https://github.com/pAulseperformance/awesome-pinescript) | каталог ссылок | Указатель, не индикатор |
| 889 | [everget/tradingview-pinescript-indicators](https://github.com/everget/tradingview-pinescript-indicators) | классические TA (MA, полосы, осцилляторы) | Нет SMC/футпринта/счёта 22 пунктов |
| 527 | [LuxAlgo/PineTS](https://github.com/LuxAlgo/PineTS) | транспилятор Pine → JS | Движок, не SMC. Сам LuxAlgo SMC на GitHub **не лежит** |
| 451 | [just-nilux/awesome-tradingview](https://github.com/just-nilux/awesome-tradingview) | каталог стратегий/алертов | Указатель |
| 301 | [codenamedevan/pinescriptv6](https://github.com/codenamedevan/pinescriptv6) | markdown-справка Pine v6 для LLM | Там есть сигнатура `request.footprint()`, кода продукта нет |
| 43 | [Ahmed-GoCode/Quant-Edge-Indicators](https://github.com/Ahmed-GoCode/Quant-Edge-Indicators) | **16 отдельных** скриптов v6: SMC + Fib + RSI + черепахи | Максимум звёзд среди *тематических* SMC-наборов. Это пачка файлов, не одна машина входа/выхода |
| 41 | [brandononchain/opentrade](https://github.com/brandononchain/opentrade) | AI-агент для написания Pine | Генератор, не индикатор |
| 28 | [samiath17/smc-tradingview-indicator](https://github.com/samiath17/smc-tradingview-indicator) | один короткий v5: FVG-коробки + EMA + «свип» по `ta.cross` | Учебный каркас. Свип = пересечение линии максимума, не wick+close |
| 19 | [abbaselmas/tradingview-indicator-combination](https://github.com/abbaselmas/tradingview-indicator-combination) | склейка VP + уровни + FVG + SMC | Старый комбайн; автор сам пишет «free version hack» |
| 16 | [traderdiegox/Tradingview-Indicators](https://github.com/traderdiegox/Tradingview-Indicators) | набор ICT-скриптов | Модули по отдельности |
| 15 | [sonnyparlin/fvg_pinescript](https://github.com/sonnyparlin/fvg_pinescript) | только FVG | Один пункт из 22 |
| 13 | [Mrshahidali420/ORB-Multi-Model-Indicator](https://github.com/Mrshahidali420/ORB-Multi-Model-Indicator) | 9 моделей ORB + confidence score | Сессия NY, не футпринт/SMC-сюит |
| 12 | [chris-c-thomas/chrd-tradingview-pine-scripts](https://github.com/chris-c-thomas/chrd-tradingview-pine-scripts) | SPY 0DTE: **взвешенный счёт + `request.footprint()`** | Ближе всех по *сборщику*. Рынок — опционы SPY, не крипто-перп. 1-мин вариант футпринт **не** кладёт в сигнал |
| 11 | [itsabubakarshf/pinescript-v6-gxt-toolkit](https://github.com/itsabubakarshf/pinescript-v6-gxt-toolkit) | skill/KB для ICT/GxT (SMT, FVG, confluence engine) | Заготовка под генерацию, не готовый overlay |
| 8 | [yusin99/…Smart-money-concepts](https://github.com/yusin99/Tradingview-Pinescript-Indicator---Smart-money-concepts) | старый SMC v5 | Геометрия |
| 6 | [casoon/pine-scripts](https://github.com/casoon/pine-scripts) | библиотеки RTA: структура, VP, Wyckoff, ликвидность | Модульный конструктор, не один продукт |
| 6 | [DeolinNaidoo/TradingView-Larper-Indicator](https://github.com/DeolinNaidoo/TradingView-Larper-Indicator) | SMT, CISD, FVG, Quarterly Theory | ICT-надстройка |
| 5 | [lildibbb/smc-mtf-tradingview](https://github.com/lildibbb/smc-mtf-tradingview) | MTF FVG/OB/BOS | Карта |
| 3 | [CedInvest/sm-radar-pine](https://github.com/CedInvest/sm-radar-pine) | бесплатный SMC для крипты | Карта |
| 1 | [Synvoya/Confluence](https://github.com/Synvoya/Confluence) | **15 модулей SMC/ICT в одном v6** | Лучшее совпадение по *карте и сессиям*. На GitHub почти не видно; жизнь — на TV |
| 1 | [Robwhitlow3/tradingview-orderflow-indicators](https://github.com/Robwhitlow3/tradingview-orderflow-indicators) | честная дельта с LTF 1s, CVD, absorption | Лучшее совпадение по *потоку без вранья*. Автор прямо пишет: это не бид/аск, ~70–85% на ликвидных фьючерсах |
| 1 | [quantumalgo-official/smart-money-concepts-indicator](https://github.com/quantumalgo-official/smart-money-concepts-indicator) | SMC v6, MIT, июль 2026 | Свежий клон LuxAlgo-класса |
| 1 | [gabrielkoerich/smart-money-concepts](https://github.com/gabrielkoerich/smart-money-concepts) | TypeScript SMC + confluence scoring 100+ | Не TradingView |
| 0 | [1VB0/Delta-Footprints](https://github.com/1VB0/Delta-Footprints), [1VB0/Flow-Engine](https://github.com/1VB0/Flow-Engine) | delta / VP divergence, август 2026 | Сырые эксперименты |
| 0 | [danielvngit/PineScript_PDArray_Indicator](https://github.com/danielvngit/PineScript_PDArray_Indicator) | 18 переключаемых PD-массивов ICT (сент. 2026) | Свежий, без аудитории |
| 0 | [CaidynAW/Apex-Indicator](https://github.com/CaidynAW/Apex-Indicator) | «Adaptive SMC Intelligence», HTF dashboard, март 2026 | Заявка совпадает по словам, звёзд нет |
| 0 | десятки `jayadevrana/pinescript-fvg-*` | SEO-клонферма нулевых репозиториев | Не смотреть |

### 3.2. TradingView: настоящий «топ 2026» того же жанра

GitHub здесь вторичен. Цифры с карточек скриптов на 2026-09-05:

| Скрипт | Площадка | Оценка масштаба | Что умеет | Чего нет |
|---|---|---|---|---|
| [Smart Money Concepts (SMC) LuxAlgo](https://www.tradingview.com/script/CnB3fSph-Smart-Money-Concepts-SMC-LuxAlgo/) | TV, open-source | **~4.8 млн** применений, **~164 тыс.** бустов, обновление 2025-09-23 | BOS/CHoCH internal+swing, OB, EQH/EQL, FVG, premium/discount, PDH/PWH | Футпринт, дельта, счёт входа, выход, AMD бара, айсберг, гамма |
| LuxAlgo PAC / Premium | TV, invite-only | вендор заявляет «5M+ users» на всю линейку; цифра рекламная | volumetric OB, MTF дашборд, скринер | Исходника на GitHub нет. Это не Nexus |
| [Synvoya Confluence (SMC)](https://www.tradingview.com/script/QP9mGNIG-Synvoya-Confluence-SMC/) | TV + [GitHub](https://github.com/Synvoya/Confluence) | 1 ★ на GH; позиционирование «самый полный бесплатный SMC» | 15 модулей: структура, OB/breaker, FVG/iFVG, EQH/EQL/sweep, сессии/killzones/Silver Bullet, CRT, ADR/Judas, SMT, MTF bias, алерты на close | Нет `request.footprint`, нет счёта long/short с вето, нет выхода. Чеклист = контекст, **не** стрелка |
| [TB Smart Money Concept 2026](https://www.tradingview.com/script/IM2GxnOK-TB-Smart-Money-Concept-2026/) | TV | новый «2026» в названии | BOS/MSS + ATR displacement, Origin Cells, FVG+CE, sweeps, Bias HUD | Геометрия. Пивоты подтверждаются через N баров |
| TradingIQ OrderFlow IQ | TV | коммерческий OF-сюит | footprint/delta/CVD/iceberg *по тикам TV*, не GitHub | Не SMC-карта 22 пунктов; тиковый OF ≠ стакан |
| martineye15 Orderflow Suite, LunqFX Delta VP, Devtrader OF+VP, crossresearch Liquidity Map+VP+OF | TV | средний тир комьюнити | дельта-прокси + профиль ± FVG/OB | Большинство **сами пишут**: бид/аск нет; дельта = LTF или `(close-low)/range` |

LuxAlgo SMC — это де-факто мировой шаблон 2022–2026. Почти все GitHub-репозитории из таблицы 3.1 либо копируют его геометрию, либо режут её на куски.

---

## 4. Три ближайших родственника (не клоны)

Нexus из спецификации = **карта × поток × сборщик**. На рынке эти три слоя почти всегда продают порознь.

### A. Карта (SMC/ICT) — победитель: LuxAlgo / Synvoya

Покрывают пункты примерно **8, 9, 10 (частично), 13 (EMA), 19, 20**.  
Не покрывают **1 (AMD бара), 3, 6 (eaten по объёму), 12 как футпринт, 15 как 3:1 ряд, 16, 17, 4+выход**.

Synvoya честнее LuxAlgo-клонов в двух местах: алерты на закрытой свече и явная подпись «чеклист — не сигнал». Это ближе к правилу Nexus «не стрелять с середины бара».

### B. Поток (дельта / CVD / футпринт) — победитель честности: Robwhitlow; победитель API 2026: chris-c-thomas

| | Robwhitlow TV OF | chris-c-thomas SPY 15m | Nexus (спека) |
|---|---|---|---|
| Источник дельты | `request.security_lower_tf` 1s, close>open = ask | `request.footprint()` | `request.footprint()` |
| Автор признаёт ограничение | да, 70–85% vs настоящий футпринт | да, realtime ≠ history, футпринт перерисовывается *внутри* бара | да, вход только `barstate.isconfirmed` |
| Счёт | нет (маркеры absorption/div) | да, вес 2× структура + 1× подтверждения, порог 7 из 16 | да, `S_long`/`S_short`, порог 8, **жёстко: карта≥1 и поток≥2** |
| Рынок | любые объёмные | заточен под SPY 0DTE + NYSE TICK | любой символ с футпринтом, крипто-перп ок |
| SMC/FVG/сессии UTC | нет | уровни дня/VWAP, не ICT-сюит | да |
| Выход | нет | нет машины позиции | стоп/тейк/eaten/трейл |

Это единственный найденный на GitHub продукт 2026, который **уже склеивает `request.footprint()` со скорингом**. Но:

- на 1-минутном варианте футпринт **только в таблицу**, в сигнал не идёт (автор знает про перерисовку);
- на 15-минутном дельта идёт как **+1 confirmation**, не как обязательный поток;
- нет правила «без футпринта нет входа»;
- нет 22 модулей.

Учебники 2026 (`supa.is`, TradersPost, Jayadev Rana) показывают гистограмму дельты на 15 строк. Продукта из них нет.

### C. «Агенты» — TradingAgents, не индикатор

102 тыс. звёзд. Python. Аналитик → дебаты → трейдер → риск.  
В ТЗ пункт 21 копирует **роли и запрет усреднения**, не нейросеть на графике. Ставить TradingAgents «вместо индикатора» нельзя: нет Pine, нет футпринта TV, нет L2.

---

## 5. Матрица 22 пунктов: есть / нет

Обозначения: **+** есть по сути, **~** похоже по названию, **−** нет или бутафория.

| # | Пункт Nexus | LuxAlgo SMC | Synvoya | Quant-Edge | Robwhitlow | SPY scalper (GH) |
|---|---|---|---|---|---|---|
| 1 | AMD бара (накопление/свип/раздача) | − | − | − | ~ absorption | − |
| 2 | Карта ликвидности = POC/VAH/VAL сессии + толстые ряды | − (EQH/EQL, не аукцион) | − | − | ~ leg POC | ~ барный POC/VA |
| 3 | Крупный ряд ≥5× медианы в зоне | − | − | − | ~ z-score delta | − |
| 4 | Счёт входа, порог | − | − (чеклист) | стрелки в отдельных скриптах | − | **+** (7/16) |
| 5 | Дашборд статуса | − | + bias table | + в части скриптов | − | **+** 31 строка |
| 6 | Снятие уровня / eaten | ~ mitigation OB | ~ sweep label | ~ Trio Liquidity | − | − |
| 7 | Все пороги как Inputs с происхождением | ~ settings | + | + | + | + |
| 8 | HTF закрытый / LTF поток | ~ MTF highs | + Struct+EMA | ~ multilayer RSI | − | + 5m confirm |
| 9 | FVG / BAG | + FVG | + FVG/iFVG/CE | + FVG/IFVG | − | − |
| 10 | Сессии + профиль прошлой | − | **+** Asia/Lon/NY + macros | − | session CVD | RTH/ORB, не UTC-триада |
| 11 | Fib OTE как фильтр, не тейк | − | premium/discount 50% | + Fib+FVG (часто как сигнал) | − | − |
| 12 | Объём = футпринт, иначе вето | − | − | − | LTF-прокси | **+ API**, вето нет |
| 13 | MA режима, кросс не стрелка | − | EMA 9/21 как bias | часто кросс = вход | − | EMA как 2× вес |
| 14 | RSI только с дивером потока | − | − | RSI соло и дивер цены | − | RSI + price div |
| 15 | Имбаланс ряда 3:1 | − | − | − | ~ \|delta\|/vol | API есть, стек рядов нет |
| 16 | Айсберг-прокси (ряд толстеет 2 бара) | − | − | − | ~ absorption | − |
| 17 | Нет GEX без цепочки; ATR ширит стоп | − | ADR exhaustion | − | − | ATR regime, не GEX |
| 18 | Боковик VAL↔VAH | premium/discount | + | − | − | squeeze / range mode |
| 19 | ICT/SMC как плюс, не соло-покупка | **+ рисует, не считает** | **+ рисует, не считает** | рисует | − | − |
| 20 | Свип: хвост + закрытие внутрь | ~ EQH taken | + sweep на close | ~ close-back boxes | − | − |
| 21 | Роли map/flow/regime/judge, конфликт = тишина | − | чеклист Bias/Liq/POI | − | − | веса, но всё в одной куче |
| 22 | Бумажные счётчики SMC vs MA vs RSI vs полный | − | − | 16 скриптов рядом, не A/B | − | − |
| — | Машина выхода (стоп/тейк/трейл/eaten) | − | − | в *strategy*-файлах по отдельности | − | − |
| — | Invite-only + Protected | нет (открыт) | открыт | открыт | открыт | открыт |

Итог: **полное пересечение с Nexus = пусто**. Ближе всего *склеить* Synvoya (карта+сессии) и SPY scalper / Robwhitlow (поток+счёт) — и всё равно останутся AMD, eaten, вето «карта×поток», выход и пункт 22.

---

## 6. Что в 2026 называют «топом», но брать нельзя как основу

1. **Репозитории с 0 звёзд и одинаковым README** (`jayadevrana/pinescript-fvg-*` и клоны). Это посев под поиск, не код.
2. **Скрипты с «AI» в названии** на TV и GH (`Ultimate Trend Suite [AI]` и т.п.). Обычно MA+RSI+Supertrend.
3. **Invite-only с «8 из 10»** — разобрано в `docs/TV-CLOSED-SCRIPTS-WINRATE.md`. Модераторы TV такие скрипты не аудитят.
4. **TradingAgents как «индикатор 2026»**. Топ GitHub года в трейдинге, но другая категория.
5. **Дельта вида `(close−low)/range`**, которую честно описывает LunqFX. Это не футпринт и не стакан. В Nexus так подставлять покупку запрещено.

---

## 7. Практический вывод для продукта

| Вопрос | Ответ |
|---|---|
| Есть ли на GitHub готовый топ-2026 «как заказано»? | Нет |
| Есть ли что смотреть глазами, не копируя код в этот репозиторий? | Да: LuxAlgo SMC (геометрия), Synvoya (комбайн+сессии+no-repaint alerts), Robwhitlow (честная дельта), chris-c-thomas 15m (счёт + `request.footprint`) |
| Стоит ли форкать LuxAlgo и «добавить 22 пункта»? | Нет. House Rules TV запрещают перепубликовать их исходник. Геометрию можно писать заново |
| Стоит ли ждать, что GitHub сам родит такой сюит? | `request.footprint()` вышел в январе 2026. За 8 месяцев звёздных обёрток почти нет. Окно открыто: продукт ещё не занят |
| Меняет ли поиск спецификацию Nexus? | Нет. Поиск подтверждает дыру: карта и поток живут в разных скриптах; сборщик со вето «карта×поток» и машиной выхода в топе отсутствует |

Код Capitalizator и любой внутренний стол в этом поиске не участвовали.

---

## 8. Источники (срез 2026-09-05)

- GitHub Search API, публичные карточки репозиториев из таблиц выше  
- [LuxAlgo SMC на TradingView](https://www.tradingview.com/script/CnB3fSph-Smart-Money-Concepts-SMC-LuxAlgo/) — 4 811 040 применений, 164 100 бустов  
- [Synvoya/Confluence README](https://github.com/Synvoya/Confluence) и [карточка TV](https://www.tradingview.com/script/QP9mGNIG-Synvoya-Confluence-SMC/)  
- [Ahmed-GoCode/Quant-Edge-Indicators](https://github.com/Ahmed-GoCode/Quant-Edge-Indicators)  
- [Robwhitlow3/tradingview-orderflow-indicators](https://github.com/Robwhitlow3/tradingview-orderflow-indicators)  
- [chris-c-thomas SPY 0DTE 15m](https://github.com/chris-c-thomas/chrd-tradingview-pine-scripts) — взвешенный счёт и `request.footprint()`  
- Справка Pine: `request.footprint()` — Premium/Ultimate, один вызов на скрипт, дефолт имбаланса 300% (3:1)  
- Спека продукта: `docs/TV-STANDALONE-INDICATOR.md`

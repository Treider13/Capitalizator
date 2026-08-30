# Census: GitHub repos close to S/R, volume profile, order flow, SMC/ICT, BTC-filters, multi-agent “teams”

**Date:** 2026-08-30 · **Method:** GitHub Search + `gh repo view` / `gh issue list` (live metadata). ~40 search queries, 350+ unique hits, 210+ repos viewed. Stars and `pushedAt` are **as of 2026-08-30**.

**Deduped (famous engines — not re-reviewed here):** `freqtrade/freqtrade`, `hummingbot/hummingbot`, `nautechsystems/nautilus_trader`, `jesse-ai/jesse`, `ccxt/ccxt`, `TauricResearch/TradingAgents`, `NoFxAiOS/nofx`, FinMem (`pipiku915/FinMem-LLM-StockTrading`), `nkaz001/hftbacktest`, `bmoscon/cryptofeed`, `c9s/bbgo`. They appear only as **hosts** of strategies or as contrast.

**PnL tags:** `[V]` third-party / on-chain / issue-corroborated · `[S]` author or user self-report with operational detail · `[M]` marketing / screenshot / Telegram · `—` none found.

**Honest headline:** almost all S/R, volume-profile, SMC/ICT, Wyckoff, and “bounce vs breakout” GitHub is unused indicator code or empty READMEs. The bots people actually run are **grid / DCA / grind / RSI-EMA / market-making**. The ideas in the query exist as **libraries and charts**, not as live PnL systems.

---

## The ~15 that have real issues, users, or practice

These are the only ones in this census where strangers filed operational bugs, compared live vs backtest, or asked “how do I run this with $500”. None publish an audited track record.

| # | Repo | ★ | What they actually run | Practice evidence | PnL |
|---|---|---|---|---|---|
| 1 | [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) | 3381 | Freqtrade **X7** grind/DCA on spot+futures. Not S/R, not SMC. RSI/EMA/volume tags + averaging down. | 76 issues. 2026-08 live: owner discusses X7 “top coins mode” fills (XRP/OP/SUI/WLD) [#1234](https://github.com/iterativv/NostalgiaForInfinity/issues/1234); users on $440–$500 setups [#1049](https://github.com/iterativv/NostalgiaForInfinity/issues/1049); futures grind-near-liquidation [#1038](https://github.com/iterativv/NostalgiaForInfinity/issues/1038); profit distortion in grind [#1084](https://github.com/iterativv/NostalgiaForInfinity/issues/1084); backtest≠live entry prices. Discord is the real community. | Mixed `[S]`. Users report grind recoveries **and** “X7 low performance”. No `[V]` book. |
| 2 | [enarjord/passivbot](https://github.com/enarjord/passivbot) | 2082 | Recursive **grid / trailing** on Bybit/OKX/Binance/Bitget/Hyperliquid perps. | 78 issues. Live: duplicate trailing entries [#980](https://github.com/enarjord/passivbot/issues/980), Bybit restart deadlock [#1323](https://github.com/enarjord/passivbot/issues/1323), TWEL auto-reduce looping with entries [#600](https://github.com/enarjord/passivbot/issues/600), Bybit UNIFIED balance double-count. Owner patches from live reports. | Community `[S]` on Discord: grids print in ranges, get run over in trends. No `[V]`. |
| 3 | [Haehnchen/crypto-trading-bot](https://github.com/Haehnchen/crypto-trading-bot) | 3516 | JS bot, Bitmex/Binance/Bitfinex, dip-catcher + several TA strategies. Futures-capable. | 110 issues, years of “websocket error / add exchange / how do I add a BTC filter to dip_catcher” [#358](https://github.com/Haehnchen/crypto-trading-bot/issues/358). Real operators, not stars. | `[S]` scattered. No audited book. |
| 4 | [ctubio/Krypto-trading-bot](https://github.com/ctubio/Krypto-trading-bot) | 3709 | Self-hosted **C++ market maker** (both sides of the book). Last push 2024-12. | 64 issues. Users still file Binance NOTIONAL / segfault / “is this project dead?” [#1188](https://github.com/ctubio/Krypto-trading-bot/issues/1188). That question only appears when people were running it. | MM `[S]`. Typical tiny accounts lose to fees. |
| 5 | [c9s/bbgo](https://github.com/c9s/bbgo) *(engine, listed only as practice host)* | 1657 | Go framework; **grid2** is what users run. | 112 issues. Live: “grid2 stuck after stop-loss” [#1764](https://github.com/c9s/bbgo/issues/1764), multi-session param overwrite, futures short backtest ask. TW community. | Grid `[S]`. |
| 6 | [51bitquant/binance_grid_trader](https://github.com/51bitquant/binance_grid_trader) | 975 | Binance spot+**futures grid**. Chinese docs. | 12 issues, all operational: tick-size rejects, hedge mode, leverage on futures, Gate.io. | Grid `[S]`. |
| 7 | [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6490 | Consumer bot: Grid / DCA / TradingView / LLM evaluator. | 153 issues. 2026-08: GridTradingMode backtest vs live fee behavior [#3656](https://github.com/Drakkar-Software/OctoBot/issues/3656), TV signals on futures InsufficientFunds, OKX EEA/MiCA auth. People run this. | Grid/DCA `[S]`. |
| 8 | [TheFourGreatErrors/alpha-rptr](https://github.com/TheFourGreatErrors/alpha-rptr) | 690 | Multi-exchange **futures** bot (Binance/Bybit/BitMEX). Strategy plugin style. | Live SL/TP/trailing argument-shift bug on Binance Futures & Bybit [#85](https://github.com/TheFourGreatErrors/alpha-rptr/issues/85) — only filed if you were exiting live. | — |
| 9 | [conor19w/Binance-Futures-Trading-Bot](https://github.com/conor19w/Binance-Futures-Trading-Bot) | 660 | TA bot on USDT-M. Last real push 2024-07. | 12 issues: trailing-stop field case bug (Binance drops the order) [#77](https://github.com/conor19w/Binance-Futures-Trading-Bot/issues/77), ATR SL/TP, one-way mode. Fork bait. | — |
| 10 | [cunarist/solie](https://github.com/cunarist/solie) | 59 | GUI **Binance futures** bot. Small but real. | 15 issues: 1s candles, multi-TP, frozen UI, “auto transaction should get the exact indicator row”. | — |
| 11 | [joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) | 1965 | **Library**, not a bot. Python port of LuxAlgo SMC (BOS/CHoCH/OB/FVG/liquidity). | 19 issues. Critical: **lookahead in `swing_highs_lows()` inflates backtests** [#101](https://github.com/joshyattridge/smart-money-concepts/issues/101); streaming OB inconsistency [#93](https://github.com/joshyattridge/smart-money-concepts/issues/93); “how to generate TP for live signals?” [#106](https://github.com/joshyattridge/smart-money-concepts/issues/106). This is the SMC package people actually import. | No trading PnL. Used as a **signal toy**. |
| 12 | [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) | 5418 | Official sample pack (Supertrend, ADX-SMA, …). | 12 issues. Users: “all strategies make crap profits” [#333](https://github.com/freqtrade/freqtrade-strategies/issues/333); “won’t work live on Binance futures” [#308](https://github.com/freqtrade/freqtrade-strategies/issues/308); Weiss Wave OI request [#311](https://github.com/freqtrade/freqtrade-strategies/issues/311). Samples, not edges. | Official backtests only. |
| 13 | [OctopusTakopi/funding-rate-alpha](https://github.com/OctopusTakopi/funding-rate-alpha) | 39 | Research, not a bot. Survivorship-free funding→return test, 6.1M settings. | Reproducible notebook. Numbers already in `market-analysis.md`: tradable variant **8.9 bp/day, Sharpe 1.42**. | `[S]` research (author). Closest thing to documented futures *edge* in this census. |
| 14 | [sammchardy/python-binance](https://github.com/sammchardy/python-binance) | 7207 | Exchange SDK. Not a strategy. | **506 open issues** — the front line of Binance breakage. Every futures bot in this file depends on this or ccxt. | n/a |
| 15 | [tardis-dev/tardis-python](https://github.com/tardis-dev/tardis-python) + [tardis-node](https://github.com/tardis-dev/tardis-node) + [tardis-machine](https://github.com/tardis-dev/tardis-machine) | 147 / 366 / 310 | Tick/L2 historical + local replay server. | What serious order-flow people *use* when they are not writing a bot. Paid data. No strategy. | n/a |

**Not in the 15, but adjacent practice:** `jesse-ai/example-strategies` (177★, examples only; live is a paid plugin), `hummingbot/hummingbot-api` (140★, orchestrates multiple bots), `freqtrade/frequi` (1059★), `oliver-zehentleitner/unicorn-binance-websocket-api` (736★, 5 issues — used), `bybit-exchange/pybit` (669★).

---

## A. Support / resistance · pivots · volume profile · market profile

**What works in practice:** `py-market-profile` as a **calculator** (users compare POC/VAH/VAL to TradingView and argue). `freqtrade/technical` as an indicator bag for bots that already run. Everything else is a notebook, a Streamlit, or a 2018 dead bot.

**Bounce vs breakout:** almost nobody implements this as a named system. Closest: NFI grind (averages into a dip = implicit bounce), PatternPy (H&S etc., detection quality disputed), stolgo (price-action API, academic-issue spam). No live bounce/breakout bot with users.

| Repo | ★ | Last push | What is in the repo | Practice vs paper | PnL |
|---|---|---|---|---|---|
| [bfolkens/py-market-profile](https://github.com/bfolkens/py-market-profile) | 404 | 2023-10 | Pandas Market/Volume Profile: POC, VAH/VAL, value area. **0 open issues** (tracker quiet). Closed: “this is not market profile” [#14](https://github.com/bfolkens/py-market-profile/issues/14), POC ≠ TradingView [#16](https://github.com/bfolkens/py-market-profile/issues/16) [#10](https://github.com/bfolkens/py-market-profile/issues/10), value area wrong [#2](https://github.com/bfolkens/py-market-profile/issues/2). | Library used by hobbyists. Stale. Not a bot. | — |
| [srlcarlg/srl-python-indicators](https://github.com/srlcarlg/srl-python-indicators) | 50 | 2026-01 | **Best OSS indicator suite in this group:** Order Flow Ticks, Volume/TPO profile, Weis & Wyckoff, mplfinance/plotly. 1 issue (“how do I use this”). | Charts. No execution. | — |
| [freqtrade/technical](https://github.com/freqtrade/technical) | 1031 | 2026-08 | Indicators collected for Freqtrade (pivots, Ichimoku, …). | Used **inside** practiced bots. Not S/R logic by itself. | — |
| [keithorange/PatternPy](https://github.com/keithorange/PatternPy) | 475 | 2024-02 | Vectorized chart patterns. Issue [#13](https://github.com/keithorange/PatternPy/issues/13): “Detection is garbage quality”. | Paper. | — |
| [stockalgo/stolgo](https://github.com/stockalgo/stolgo) | 347 | 2026-07 | Price-action “APIs”. 33 issues — mostly paper-title spam, not users. | Looks alive, little trading evidence. | — |
| [judopro/Stock_Support_Resistance_ML](https://github.com/judopro/Stock_Support_Resistance_ML) | 115 | 2021-05 | K-means clustering of S/R on stocks. | Student paper. Dead. | — |
| [albertsl/support-resistance_trading-bot](https://github.com/albertsl/support-resistance_trading-bot) | 34 | 2018-06 | Bot that “trades any asset on S/R”. | Dead 8 years. Empty practice. | — |
| [Coelodonta/Machine_Learning_Support_Resistance](https://github.com/Coelodonta/Machine_Learning_Support_Resistance) | 18 | 2021-06 | Unsupervised S/R. | Notebook. | — |
| [steveyx/SupportResistTradingTestUsingPandas](https://github.com/steveyx/SupportResistTradingTestUsingPandas) | 8 | 2018-05 | Pandas S/R test. | Dead. | — |
| [cenobar/TPO](https://github.com/cenobar/TPO) | 22 | 2021-08 | Market profile + volume profile. | Dead calculator. | — |
| [VanHes1ng/Cryptocurrencies-volume-profile](https://github.com/VanHes1ng/Cryptocurrencies-volume-profile) | 8 | 2024-12 | Streamlit VP for crypto. | Demo app. | — |
| [QuantextCapital/MarketProfile](https://github.com/QuantextCapital/MarketProfile) | 8 | 2024-09 | “For my YT content”. | Content, not a system. | — |
| [Aissat-Kamel/volume_profile](https://github.com/Aissat-Kamel/volume_profile) | 6 | 2021-08 | Tiny VP snippet. | Unused. | — |
| [s-kust/anchored_vwaps](https://github.com/s-kust/anchored_vwaps) | 11 | 2024-12 | Anchored VWAP overlay on OHLC. | Plot helper. | — |
| [KenjiLoo/volume-profile-bot](https://github.com/KenjiLoo/volume-profile-bot) | 1 | 2026-02 | “Perp futures on VP standard-deviation”. | Empty-README class. **The only named VP futures bot found.** 0 issues. | — |
| [bukosabino/ta](https://github.com/bukosabino/ta) | 5181 | 2026-03 | Generic TA (includes pivots). | Library. | — |
| [peerchemist/finta](https://github.com/peerchemist/finta) | 2264 | 2022-07 | Generic TA. **Archived.** | Dead library. | — |
| [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) | 12218 | 2026-08 | Canonical TA wrapper. | Infra. | — |
| [matplotlib/mplfinance](https://github.com/matplotlib/mplfinance) | 4427 | 2024-08 | Candle plots (can draw VP-ish histograms). | Viz. | — |
| [highfestiva/finplot](https://github.com/highfestiva/finplot) | 1181 | 2026-03 | Fast finance plots; used by stack-orderflow. | Viz. | — |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 8910 | 2026-08 | Vectorized backtester. Commons Clause on Pro. | Research. People backtest S/R *here*, they do not ship it. | — |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 8912 | 2026-08 | Simple OHLC backtester. | Research. | — |
| [mementum/backtrader](https://github.com/mementum/backtrader) | 23016 | 2024-08 | Classic backtester. Issues disabled. | Stagnant host. | — |

`twopirllc/pandas-ta` and `pandas-ta/pandas-ta` **do not resolve** on 2026-08-30 (deleted / moved). A widely used pivot/VWAP library vanished — typical of this layer.

---

## B. Order book · order flow · footprint · tape

**What works in practice:** data pipes (Tardis, cryptofeed, unicorn WS, python-binance). Visualizers (heatmap, footprint) that people screenshot. Academic LOB models that do not trade.

**What does not exist as a practiced OSS bot:** a footprint / CVD / tape-reading **execution** system with users. Closest attempts are personal MT5 scalpers and a 22★ Bitfinex BSI bot with 0 issues.

| Repo | ★ | Last push | Implemented | Practice vs paper | PnL |
|---|---|---|---|---|---|
| [Elenchev/order-book-heatmap](https://github.com/Elenchev/order-book-heatmap) | 510 | 2021-03 | L2 heatmap vs trades. | Viz. Dead 5 years. | — |
| [murtazayusuf/OrderflowChart](https://github.com/murtazayusuf/OrderflowChart) | 249 | 2024-09 | Plotly **footprint**. Archived. Issues: “will it work realtime?” [#5](https://github.com/murtazayusuf/OrderflowChart/issues/5), “any plan for streaming?” [#1](https://github.com/murtazayusuf/OrderflowChart/issues/1). | Charts only. | — |
| [tysonwu/stack-orderflow](https://github.com/tysonwu/stack-orderflow) | 138 | 2023-02 | Footprint GUI (finplot + pyqtgraph). 8 issues. | Desktop viz. Stale. | — |
| [AndreaFerrante/Orderflow](https://github.com/AndreaFerrante/Orderflow) | 137 | 2026-08 | Tick→orderflow reshape **package**. Pushed 2026-08. 0 open issues. | Library. “how to use this module?” | — |
| [akenshaw/btcusdt-orderflow](https://github.com/akenshaw/btcusdt-orderflow) | 41 | 2023-12 | Realtime BTCUSDT GUI. | Personal viz. | — |
| [mahmoud20138/OrderFlow-Analysis-Pro](https://github.com/mahmoud20138/OrderFlow-Analysis-Pro) | 43 | 2026-04 | Bybit + MT5 footprint / delta. | Personal desk. 0 issues. | — |
| [mahmoud20138/OrderFlow-Scalper](https://github.com/mahmoud20138/OrderFlow-Scalper) | 14 | 2026-03 | 3-thread MT5 footprint scalper. | Personal. 1 issue. | — |
| [tapedelta/kline-orderbook-chart](https://github.com/tapedelta/kline-orderbook-chart) | 31 | 2026-07 | Heatmap + footprint + **liquidation heatmap**. | Charting, not a bot. | — |
| [alpacahq/example-hftish](https://github.com/alpacahq/example-hftish) | 868 | 2023-07 | Official Alpaca **order-book imbalance** example (US stocks). | Tutorial. Not crypto. | — |
| [nkaz001/algotrading-example](https://github.com/nkaz001/algotrading-example) | 323 | 2023-12 | OBI backtests (companion to hftbacktest). | Research. | — |
| [sadighian/crypto-rl](https://github.com/sadighian/crypto-rl) | 966 | 2022-01 | Record/replay crypto LOB + RL. | Dead toolkit. Important idea, no live. | — |
| [zcakhaa/DeepLOB-…](https://github.com/zcakhaa/DeepLOB-Deep-Convolutional-Neural-Networks-for-Limit-Order-Books) | 606 | 2021-07 | Canonical DeepLOB notebook. FI-2010. Issue #17 (label leakage) already in `market-analysis.md`. | Paper. **Not tradeable.** | — |
| [Crypto-toolbox/HFT-Orderbook](https://github.com/Crypto-toolbox/HFT-Orderbook) | 1384 | 2024-11 | In-process LOB matching structure. | Engine brick. | — |
| [mdibo/Avellaneda-Stoikov](https://github.com/mdibo/Avellaneda-Stoikov) | 155 | 2020-05 | AS-HFT MM replication. | Paper clone. | — |
| [ragoragino/avellaneda-stoikov](https://github.com/ragoragino/avellaneda-stoikov) | 94 | 2017-10 | Older AS replication. | Paper clone. | — |
| [andrewlfc7/BFX-BSI](https://github.com/andrewlfc7/BFX-BSI) | 22 | 2024-08 | Bitfinex **BSI orderflow bot**. 0 issues. | Personal attempt. Only named “orderflow trading bot” with code that looks like a bot. | — |
| [we-z/Orderbook-HFT](https://github.com/we-z/Orderbook-HFT) | 11 | 2022-11 | OBI strategy sketch. | Unused. | — |
| [AndresRzCh/lob-cnn-trader](https://github.com/AndresRzCh/lob-cnn-trader) | 14 | 2022-07 | LOB-CNN trader. Archived. | Thesis. | — |
| [LesterCS/Decoding-Institutional-Order-Flow-in-Python-like-ICT](https://github.com/LesterCS/Decoding-Institutional-Order-Flow-in-Python-like-ICT) | 15 | 2023-04 | ICT-flavoured “order flow” indicator. | YouTube-adjacent. | — |
| [elicat001/btc_quant_industrial-](https://github.com/elicat001/btc_quant_industrial-) | 12 | 2026-02 | BTC signals: order flow + factors + ML. | Personal, 0 issues. | — |
| [oliver-zehentleitner/unicorn-binance-local-depth-cache](https://github.com/oliver-zehentleitner/unicorn-binance-local-depth-cache) | 52 | 2026-08 | Local L2 cache SDK. | Infra people use. | — |
| [oliver-zehentleitner/unicorn-binance-websocket-api](https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api) | 736 | 2026-08 | Binance WS SDK. | Infra. | — |
| [crypto-chassis/ccapi](https://github.com/crypto-chassis/ccapi) | 732 | 2026-08 | C++ header-only exchange + bindings. | Infra. | — |
| [microsoft/MarS](https://github.com/microsoft/MarS) | 1777 | 2026-06 | Generative **market simulator**. | Research. Not a trader. | — |
| [jpmorganchase/abides-jpmc-public](https://github.com/jpmorganchase/abides-jpmc-public) | 174 | 2024-07 | ABIDES fork. Archived. | Research. | — |
| [databento/databento-python](https://github.com/databento/databento-python) | 296 | 2026-08 | Official Databento client (equities/futures L3). | Paid data. | — |
| [jamesmawm/High-Frequency-Trading-Model-with-IB](https://github.com/jamesmawm/High-Frequency-Trading-Model-with-IB) | 2920 | 2025-05 | IB HFT *model* (book example). | Educational. | — |

Bookmap / ATAS / Sierra / Quantower / Exocharts / TradingLite are **closed**. There is no OSS Bookmap.

---

## C. SMC / ICT / Wyckoff / liquidity / FVG

**Toy vs used:** one library is used (`joshyattridge/smart-money-concepts`). Everything else is MT5/Pine/XAU clones, knowledge bases, or 2025–26 AI wrappers. **No SMC/ICT/Wyckoff repo in this census has a stranger reporting live crypto-futures PnL.** Several gold (XAUUSD) EAs exist; that is a different market (FX spread, not crypto perps).

| Repo | ★ | Last push | Toy / used | Notes | PnL |
|---|---|---|---|---|---|
| [joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) | 1965 | 2026-04 | **Used library** | See §15 table. Lookahead [#101](https://github.com/joshyattridge/smart-money-concepts/issues/101) is the fact that matters. | — |
| [Prasad1612/smart-money-concept](https://github.com/Prasad1612/smart-money-concept) | 42 | 2025-09 | Toy | Another Python SMC port. 0 issues. | — |
| [KVignesh122/MT5-SMC-trading-bot](https://github.com/KVignesh122/MT5-SMC-trading-bot) | 74 | 2026-07 | Toy EA | MQL5 OB/FVG/BOS. 0 issues. | — |
| [manuelinfosec/profittown-sniper-smc](https://github.com/manuelinfosec/profittown-sniper-smc) | 74 | 2025-08 | **Sniper naming** | ICT “sniper”. Treat as G-adjacent. 0 issues. | `[M]` likely |
| [Nguyen-Phu-Cuong/Matrix-Confluence-Scorer](https://github.com/Nguyen-Phu-Cuong/Matrix-Confluence-Scorer) | 118 | 2026-07 | Toy MT5 | “2026 Pro-Level” MTF confluence + liquidity sweeps. 0 issues, 0 forks. | `[M]` tone |
| [ajayprabhuraj/institutional-orderflow-mt5](https://github.com/ajayprabhuraj/institutional-orderflow-mt5) | 121 | 2026-08 | Toy MT5 | “Real-time Order Blocks & FVG”. 2 issues. | `[M]` |
| [JustExecution/HTF_indicator](https://github.com/JustExecution/HTF_indicator) | 51 | 2026-08 | Toy | ICT/SMC MTF indicator. | — |
| [haza79/MT5-Smart-Money-Concept-Indicator](https://github.com/haza79/MT5-Smart-Money-Concept-Indicator) | 44 | 2025-08 | Toy | Ongoing SMC+PA indicator. | — |
| [samiath17/smc-tradingview-indicator](https://github.com/samiath17/smc-tradingview-indicator) | 28 | 2026-01 | Toy Pine | SMC pack for TradingView. Real SMC use is **on TradingView**, not GitHub. | — |
| [Ahmed-GoCode/Quant-Edge-Indicators](https://github.com/Ahmed-GoCode/Quant-Edge-Indicators) | 41 | 2026-08 | Toy Pine | “Professional suite”. | — |
| [sonnyparlin/fvg_pinescript](https://github.com/sonnyparlin/fvg_pinescript) | 15 | 2024-11 | Toy | Single FVG indicator. | — |
| [SrsBlack/ict-knowledge-library](https://github.com/SrsBlack/ict-knowledge-library) | 28 | 2026-08 | Knowledge base | LLM-maintainable ICT glossary. Not a bot. | — |
| [zakariab0/ozo](https://github.com/zakariab0/ozo) | 13 | 2025-01 | Toy lib | “Couldn’t find an ICT library so I wrote one”. | — |
| [brainstrme/ICT-Trading](https://github.com/brainstrme/ICT-Trading) | 8 | 2023-11 | Notes | Exploratory. | — |
| [martin254/Asian-Turtle-Soup-Trading-Bot](https://github.com/martin254/Asian-Turtle-Soup-Trading-Bot) | 15 | 2025-04 | Toy | ICT turtle-soup **forex**. | — |
| [NadirAliOfficial/STAR-EA-v11.20](https://github.com/NadirAliOfficial/STAR-EA-v11.20) | 29 | 2026-08 | Toy MT5 | 12-scenario ICT EA. | — |
| [NadirAliOfficial/trading-scanner](https://github.com/NadirAliOfficial/trading-scanner) | 13 | 2026-07 | Toy | BOS/FVG/sweep scanner. | — |
| [rcook0/SMC-ICT](https://github.com/rcook0/SMC-ICT) | 9 | 2026-02 | Toy | BTC/USD **weekend** M5/M15 EA. Odd filter. | — |
| [prashanthaitha24/nq-strategy-b-bot](https://github.com/prashanthaitha24/nq-strategy-b-bot) | 6 | 2026-05 | Toy | NQ futures: 5m inverse FVG inside 15m FVG. Long-only. | — |
| [GifariKemal/xaubot-ai](https://github.com/GifariKemal/xaubot-ai) | 70 | 2026-02 | Clone-ish | XAU + XGBoost + SMC. 5 issues. | `[M]` |
| [0xagarg/xau-ai-trading-bot](https://github.com/0xagarg/xau-ai-trading-bot) | 50 | 2026-03 | **Clone** | Same README sentence as xaubot-ai. | `[M]` |
| [lordgaruda/XAU-60](https://github.com/lordgaruda/XAU-60) | 47 | 2026-03 | Toy | WIP SMC scalper, MetaQuotes Python. | — |
| [WilliamYi951208/trading-assistant](https://github.com/WilliamYi951208/trading-assistant) | 15 | 2026-06 | Toy | Gold futures: Al Brooks + SMC + order flow. Assistant, not auto. | — |
| [YoungCan-Wang/WyckoffTradingAgent](https://github.com/YoungCan-Wang/WyckoffTradingAgent) | 590 | 2026-08 | AI wrapper | “Wyckoff agent + AI screener”. Issues are install/WeChat/DeepSeek — **no trade reports**. 0 open after burst. | — |
| [douchunzhou/Wyckoff-Reader](https://github.com/douchunzhou/Wyckoff-Reader) | 69 | 2026-05 | Reader | Chart reader, not a bot. | — |
| [XMall0808/Wyckoff-1Min-Reader](https://github.com/XMall0808/Wyckoff-1Min-Reader) | 19 | 2026-01 | Reader | 1-minute Wyckoff labels. | — |
| [Eesita/Wyckoff-AI-Assistant](https://github.com/Eesita/Wyckoff-AI-Assistant) | 22 | 2025-04 | Toy LLM | Transformer “assistant”. | — |
| [huawenmumu/wyckoff_multi_agent_analysis](https://github.com/huawenmumu/wyckoff_multi_agent_analysis) | 9 | 2025-09 | Toy | Wyckoff multi-agent **analysis**. | — |
| [heavenJiang/WyckoffPro](https://github.com/heavenJiang/WyckoffPro) | 5 | 2026-04 | Toy | “Make Wyckoff usable”. | — |
| [MurrayBakerWebDeveloper/Wyckoff-Trader](https://github.com/MurrayBakerWebDeveloper/Wyckoff-Trader) | 12 | 2015-09 | Dead | Forex Wyckoff charting, 2015. | — |
| [Steve65535/Wyckoff](https://github.com/Steve65535/Wyckoff) | 8 | 2025-11 | Point-and-figure | P&F generator. | — |
| [mrhustlex/Trading-Masters-Strategies](https://github.com/mrhustlex/Trading-Masters-Strategies) | 19 | 2026-08 | Scanners | O’Neil / swing “masters” as skills. Not SMC. | — |
| [srlcarlg/srl-python-indicators](https://github.com/srlcarlg/srl-python-indicators) | 50 | 2026-01 | Indicators | Weis & Wyckoff waves — see A. | — |

**LuxAlgo SMC lives on TradingView, not as a first-party GitHub product** (`luxalgo/smart-money-concepts` does not exist). That is where SMC is actually used.

---

## D. BTC-correlation · multi-asset regime · pairs

**Ghost town.** GitHub search `btc correlation crypto trading` and `cointegration pairs crypto` returned **0** repos. Crypto pairs-trading hits are student Catalyst leftovers and 0★ class projects. The serious pair-trading code is **equity** (Hudson & Thames, Quantopian-era, Auquan).

A “BTC filter on alts” is something practitioners *talk about* (Haehnchen issue [#358](https://github.com/Haehnchen/crypto-trading-bot/issues/358) “add BTC filter to dip_catcher”; NFI volume pairlists) but it is a **config flag**, not a researched regime system.

| Repo | ★ | Last push | What | Practice | PnL |
|---|---|---|---|---|---|
| [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | 4915 | 2023-10 | López de Prado toolkit (CUSUM, dollar bars, CPCV). **Not crypto.** | Research library. Last push 2023. | — |
| [hudson-and-thames/arbitragelab](https://github.com/hudson-and-thames/arbitragelab) | 689 | 2024-05 | Pairs / stat-arb lab (cointegration, OU, PCA). Equity-first. | Install-pain issues, not live crypto. | — |
| [je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading) | 10647 | 2026-06 | Notebook encyclopedia (pairs, cointegration, …). | Education. 0 issues. | — |
| [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | 20724 | 2026-08 | Book code (includes pairs, regime). | Education. | — |
| [Auquan/Tutorials](https://github.com/Auquan/Tutorials) | 1137 | 2020-08 | Pairs / mean-reversion tutorials. Dead. | Education. | — |
| [lamres/pairs_trading_cryptocurrencies_strategy_catalyst](https://github.com/lamres/pairs_trading_cryptocurrencies_strategy_catalyst) | 49 | 2018-12 | **The** named crypto pairs example. Built on Catalyst (dead). | Dead paper. | — |
| [eshan-kaul/PairsTrading-Crypto](https://github.com/eshan-kaul/PairsTrading-Crypto) | 12 | 2023-01 | Student pairs on crypto. | Unused. | — |
| [adnanegrb/statistical-arbitrage-crypto](https://github.com/adnanegrb/statistical-arbitrage-crypto) | 1 | 2026-07 | 528-asset dual-cointegration backtester. | New, 0 users. | — |
| [farhanarshad00/Statistical-Arbitrage_Crypto](https://github.com/farhanarshad00/Statistical-Arbitrage_Crypto) | 0 | 2026-04 | “Long-only momentum **with BTC market filter**”. | 0★. The *idea* exists as a README line. | — |
| [sujith-kamme/statistical-arbitrage-crypto](https://github.com/sujith-kamme/statistical-arbitrage-crypto) | 0 | 2026-04 | 18-asset cointegration MR. | Class project. | — |
| [mhallsmoore/qstrader](https://github.com/mhallsmoore/qstrader) | 3449 | 2024-06 | QSTrader engine (equities). | Backtest host. | — |

---

## E. Crypto futures bots with documented practice

**Deduped engines** (freqtrade, hummingbot, jesse, nautilus, bbgo) are the platforms. Below: **strategy packs and standalone futures bots** that are not those engines.

| Repo | ★ | Last push | What they run | Practice | PnL |
|---|---|---|---|---|---|
| [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) | 5418 | 2026-08 | Official samples | See §15. | Official BT only |
| [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) | 3381 | 2026-08 | X7 grind/DCA | **#1 practiced strategy on Freqtrade.** | `[S]` mixed |
| [enarjord/passivbot](https://github.com/enarjord/passivbot) | 2082 | 2026-08 | Recursive grid perps | **#1 practiced standalone futures grid.** | `[S]` mixed |
| [Haehnchen/crypto-trading-bot](https://github.com/Haehnchen/crypto-trading-bot) | 3516 | 2026-08 | JS multi-exchange | Long-lived operators. | `[S]` |
| [ctubio/Krypto-trading-bot](https://github.com/ctubio/Krypto-trading-bot) | 3709 | 2024-12 | C++ MM | Operators still compile it. | `[S]` MM |
| [51bitquant/binance_grid_trader](https://github.com/51bitquant/binance_grid_trader) | 975 | 2026-06 | Binance grid spot+fut | CN community, live rejects. | `[S]` |
| [TheFourGreatErrors/alpha-rptr](https://github.com/TheFourGreatErrors/alpha-rptr) | 690 | 2026-06 | Multi-exchange futures | Live SL/TP bugs. | — |
| [conor19w/Binance-Futures-Trading-Bot](https://github.com/conor19w/Binance-Futures-Trading-Bot) | 660 | 2024-07 | TA USDT-M | Forked a lot; last push 2024. | — |
| [Erfaniaa/binance-futures-trading-bot](https://github.com/Erfaniaa/binance-futures-trading-bot) | 405 | 2024-03 | Multi-strategy + Telegram | 8 issues. Stale. | — |
| [Hephyrius/binance_futures_bot](https://github.com/Hephyrius/binance_futures_bot) | 302 | 2022-04 | Leveraged USDT-M | 21 issues, dead 2022. | — |
| [CryptoGnome/Bybit-Futures-Bot](https://github.com/CryptoGnome/Bybit-Futures-Bot) | 120 | 2022-02 | “Liquidation hunt” | Dead. Liquidation-hunt is usually toxic. | `[M]` era |
| [cunarist/solie](https://github.com/cunarist/solie) | 59 | 2026-08 | GUI Binance futures | Small real user set. | — |
| [princeniu/AS-Grid](https://github.com/princeniu/AS-Grid) | 40 | 2025-09 | Multi-exchange futures grid | 0 issues. | — |
| [ryu878/bybit_scalp_bot_v2](https://github.com/ryu878/bybit_scalp_bot_v2) | 92 | 2026-06 | Bybit scalp; uses Binance MA as filter | 3 issues. Personal but maintained. Closest to a **cross-exchange filter**. | — |
| [ryu878/binance_futures_scalp_grid_bot](https://github.com/ryu878/binance_futures_scalp_grid_bot) | 21 | 2026-06 | BUSD grid scalp (pair may be dead). | Personal. | — |
| [tubexchat/binance_tradingbot_rocky](https://github.com/tubexchat/binance_tradingbot_rocky) | 23 | 2026-03 | **Negative funding arb** on Binance futures | Idea is real (see funding-rate-alpha). 0 issues. | — |
| [djienne/LIGHTER_Market_Making](https://github.com/djienne/LIGHTER_Market_Making) | 34 | 2026-07 | Two-sided MM on Lighter perps | New venue. 0 issues. | — |
| [djienne/COPY_WALLET_HYPERLIQUID](https://github.com/djienne/COPY_WALLET_HYPERLIQUID) | 30 | 2026-04 | Freqtrade strategy: copy a Hyperliquid wallet | Experimental, 1 issue. Copy ≠ edge. | — |
| [jesse-ai/example-strategies](https://github.com/jesse-ai/example-strategies) | 177 | 2024-03 | Official Jesse examples | Backtest only; live is paid. | — |
| [paulcpk/freqtrade-strategies-that-work](https://github.com/paulcpk/freqtrade-strategies-that-work) | 327 | 2021-06 | Name overclaims. Last push 2021. | Stale dump. | `[M]` title |
| [werkkrew/freqtrade-strategies](https://github.com/werkkrew/freqtrade-strategies) | 321 | 2021-06 | Personal pack. | Stale. | — |
| [i1ya/freqtrade-strategies](https://github.com/i1ya/freqtrade-strategies) | 244 | 2021-07 | Personal pack. | Stale. | — |
| [TheoBrigitte/freqtrade](https://github.com/TheoBrigitte/freqtrade) | 128 | 2025-04 | Strategies + **dry-run configs**. | Some dry-run artifacts. Not live books. | `[S]` dry |
| [Foxel05/freqtrade-stuff](https://github.com/Foxel05/freqtrade-stuff) | 127 | 2021-11 | Share dump. | Stale. | — |
| [Yodolescrypto/yodostrats](https://github.com/Yodolescrypto/yodostrats) | 47 | 2023-03 | “Degenerate” FT strategies. Honest README. | Stale. | — |
| [keithorange/HUGE_FreqTrade_Strategy_Collection](https://github.com/keithorange/HUGE_FreqTrade_Strategy_Collection) | 58 | 2024-04 | Scraped dump of everyone else’s strategies. | Overfit graveyard. | — |
| [keryc/crypto-bot](https://github.com/keryc/crypto-bot) | 98 | 2024-09 | NFI wrapper. Archived. | Shows NFI is what people deploy. | — |
| [anakein/beastbotXB](https://github.com/anakein/beastbotXB) | 32 | 2022-05 | FT strategy. | Dead. | — |
| [yasinkuyu/binance-trader](https://github.com/yasinkuyu/binance-trader) | 2748 | 2026-01 | “Experimental” Binance bot. **0 issues.** | Stars ≠ use. Treat as zombie. | — |
| [ghostofcor/Trading-Bot-for-Binance-Future](https://github.com/ghostofcor/Trading-Bot-for-Binance-Future) | 23 | 2025-11 | Personal futures bot. | 0 issues. | — |
| [severin-richner/binance-futures-top-traders-bot](https://github.com/severin-richner/binance-futures-top-traders-bot) | 30 | 2022-06 | Top-trader L/S ratio. Archived. | Dead idea (crowded, lagging). | — |
| [Lumiwealth/lumibot](https://github.com/Lumiwealth/lumibot) | 2009 | 2026-08 | Backtestable “AI agents” + brokers. | US-equity leaning. 65 issues. | — |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 21401 | 2026-08 | Institutional-grade engine. Crypto possible. | Engine, not a strategy. 241 issues. | — |
| [blankly-finance/blankly](https://github.com/blankly-finance/blankly) | 2468 | 2024-12 | “Build/backtest/deploy”. Quiet. | Second-tier framework. | — |
| [Quantweb3-com/NexusTrader](https://github.com/Quantweb3-com/NexusTrader) | 656 | 2026-05 | “Professional-grade” quant platform. | 3 issues. Thin practice. | — |
| [richkuo/go-trader](https://github.com/richkuo/go-trader) | 344 | 2026-08 | Go bot: backtest/paper/live + risk. | 6 issues. Young. | — |
| [barter-rs/barter-rs](https://github.com/barter-rs/barter-rs) | 2245 | 2026-08 | Rust event-driven. | Engine. 52 issues. | — |
| [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6490 | 2026-08 | Consumer. | See §15. | `[S]` |
| [Drakkar-Software/OctoBot-Tentacles](https://github.com/Drakkar-Software/OctoBot-Tentacles) | 171 | 2026-02 | Strategy packages. Archived as repo (moved). | Companion to OctoBot. | — |
| [Superalgos/Superalgos](https://github.com/Superalgos/Superalgos) | 5631 | 2026-08 | Visual crypto bot. Forks (6019) > stars — token-incentive artifact (already in `market-analysis.md`). | Lots of activity ≠ edge. | — |
| [hummingbot/gateway](https://github.com/hummingbot/gateway) | 255 | 2026-08 | DEX middleware. | Used with hummingbot. | — |
| [hummingbot/hummingbot-api](https://github.com/hummingbot/hummingbot-api) | 140 | 2026-08 | Multi-bot orchestration. | Practice host. | — |
| [freqtrade/frequi](https://github.com/freqtrade/frequi) | 1059 | 2026-08 | FT UI. | Practice host. | — |
| [hyperliquid-dex/hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) | 1810 | 2026-06 | Official HL SDK. | Infra for a venue people now actually trade. | — |
| [BowTiedDevil/degenbot](https://github.com/BowTiedDevil/degenbot) | 562 | 2026-08 | Uniswap/Curve/Solana DEX bricks. | DEX arb, not CEX futures. | — |
| [OctopusTakopi/funding-rate-alpha](https://github.com/OctopusTakopi/funding-rate-alpha) | 39 | 2026-08 | Funding predictability study | Best documented *edge* writeup. | `[S]` 8.9 bp/d |
| [blitzcrieg1/sentinel-trader-research](https://github.com/blitzcrieg1/sentinel-trader-research) | 0 | 2026-06 | LLM directional bot **no edge** + funding notes | Honest negative. | `[S]` LLM −0.24R net (see `market-analysis.md`) |
| [sammchardy/python-binance](https://github.com/sammchardy/python-binance) | 7207 | 2026-06 | SDK | 506 issues. | n/a |
| [bybit-exchange/pybit](https://github.com/bybit-exchange/pybit) | 669 | 2026-07 | Official Bybit SDK | 14 issues. | n/a |

**Nautilus / Jesse live examples:** public Jesse examples are candle strategies (EMA/RSI class), not VP/SMC. Nautilus examples are engine tutorials (order types, adapters), not a practiced S/R or order-flow strategy. Hummingbot public scripts are PMM / arb / VWAP execution — **execution algos**, not bounce/breakout.

---

## F. “Team of traders” / multi-agent that actually ran

**None of these ran a verified profitable live book as a “team”.** They are paper arenas, educational role-play, or (nofx) a terminal with a real risk clamp and a SlowMist key-leak writeup.

| Repo | ★ | Last push | Ran live? | Notes | PnL |
|---|---|---|---|---|---|
| TauricResearch/TradingAgents *(dedup)* | 101714 | 2026-07 | No execution | 3-stock 1-quarter BT, Sharpe 8.21. Independent rerun in prior research: **−25.4%**, ACM 2026: not > B&H. | `[M]` author BT |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 63086 | 2026-08 | Paper only | Buffett/Burry role-play. | — |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | 21840 | 2026-06 | Paper arena | Agent-native leaderboard (US stocks, Polymarket paper). | Arena `[S]` |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 7890 | 2026-08 | Research | Agent platform. | Paper |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16149 | 2026-07 | Research | DRL benchmarks. | Paper |
| NoFxAiOS/nofx *(dedup)* | 12781 | 2026-08 | **Yes, users try** | Go runtime clamps orders. 453 issues. SlowMist API-key leak. Closest to “LLM that can actually send an order”. | Mixed `[S]`, no `[V]` |
| [wquguru/nof0](https://github.com/wquguru/nof0) | 2749 | 2025-12 | Arena clone | Alpha Arena wave. | — |
| FinMem `pipiku915/FinMem-LLM-StockTrading` *(dedup)* | 952 | 2024-08 | Paper | Layered memory + character. Stocks. | Paper `[S]` |
| [YoungCan-Wang/WyckoffTradingAgent](https://github.com/YoungCan-Wang/WyckoffTradingAgent) | 590 | 2026-08 | Screener | See C. No live book. | — |
| [huawenmumu/wyckoff_multi_agent_analysis](https://github.com/huawenmumu/wyckoff_multi_agent_analysis) | 9 | 2025-09 | Analysis | 0 issues. | — |
| [OpenByteInc/QuantDinger](https://github.com/OpenByteInc/QuantDinger) | 11209 | 2026-08 | Platform claim | Backtest+live crypto/stocks/FX. 42 issues — product, not a published team-PnL. | `[M]` |
| [ValueCell-ai/valuecell](https://github.com/ValueCell-ai/valuecell) | 11007 | 2026-03 | Platform | Multi-agent finance. | — |
| [mnemox-ai/tradememory-protocol](https://github.com/mnemox-ai/tradememory-protocol) | 1412 | 2026-08 | Protocol | Decision memory. Not a trader. | — |
| [TradeMaster-NTU/TradeMaster](https://github.com/TradeMaster-NTU/TradeMaster) | 3054 | 2025-06 | Academic RL | NTU. | Paper |
| [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 14366 | 2026-08 | R&D agent | Not a trading desk. | — |
| [ma-pony/cryptotrader-ai](https://github.com/ma-pony/cryptotrader-ai) | ~12 | 2026 | 4 LangGraph agents | Already audited in `market-analysis.md`: 0 human issues, Dependabot only. | — |

**Bottom of F:** a “trading team” that actually ran is **nofx users** (messy, key-risk, no verified edge) and **NFI Discord** (humans + one strategy, not agents). LLM multi-agent PnL remains paper.

---

## G. Dead / scam / filtered (enough to show the filter)

| Repo | ★ | Why filtered |
|---|---|---|
| [askmike/gekko](https://github.com/askmike/gekko) | 10186 | **Archived 2020.** Once the default Node bot. Independent tests: strategies lost to B&H. |
| [DeviaVir/zenbot](https://github.com/DeviaVir/zenbot) | 8260 | **Archived.** 290 leftover issues. |
| [scrtlabs/catalyst](https://github.com/scrtlabs/catalyst) | 2560 | **Archived.** The crypto Zipline. Killed the pairs-trading examples in D. |
| [stellar-deprecated/kelp](https://github.com/stellar-deprecated/kelp) | 1127 | **Archived.** Stellar DEX MM. |
| [Ekliptor/WolfBot](https://github.com/Ekliptor/WolfBot) | 789 | Last 2023. Classic abandoned TS bot. |
| [magic8bot/magic8bot](https://github.com/magic8bot/magic8bot) | 410 | Last 2023. Mongo+Node zombie. |
| [CryptoSignal/Crypto-Signal](https://github.com/CryptoSignal/Crypto-Signal) | 5621 | Last 2024-07. Signal spam, not a futures book. |
| [mortdeus/solana-copy-sniper-mev-trading-bot](https://github.com/mortdeus/solana-copy-sniper-mev-trading-bot) | 4441 | Keyword-stuffed “free MEV sniper”. Stargazers-class. |
| [radioman/solana-trading-bot](https://github.com/radioman/solana-trading-bot) | 990 | README is the title repeated. |
| [yeahrb/CEX-Option-Futures-Crypto-Quant-Algorithm-Trading-Bot](https://github.com/yeahrb/CEX-Option-Futures-Crypto-Quant-Algorithm-Trading-Bot) | 487 | Telegram handle in the description. `[M]` |
| [0xagarg/xau-ai-trading-bot](https://github.com/0xagarg/xau-ai-trading-bot) | 50 | Clone of xaubot-ai README. |
| [manuelinfosec/profittown-sniper-smc](https://github.com/manuelinfosec/profittown-sniper-smc) | 74 | “Sniper” + ICT + 0 issues. |
| [yasinkuyu/binance-trader](https://github.com/yasinkuyu/binance-trader) | 2748 | High stars, **0 issues**, “Experimental”. Zombie. |
| [davidzr/freqtrade-strategies](https://github.com/davidzr/freqtrade-strategies) | 563 | Archived dump. |
| [paulcpk/freqtrade-strategies-that-work](https://github.com/paulcpk/freqtrade-strategies-that-work) | 327 | Title is marketing. Dead 2021. |
| `PlaceNL2026/best-of-algorithmic-trading` | — | **404** on 2026-08-30 (was a source list in earlier research). |
| `twopirllc/pandas-ta` | — | **404**. Popular TA lib gone. |
| [Hephyrius/binance_futures_bot](https://github.com/Hephyrius/binance_futures_bot) | 302 | Dead 2022, leftover issues. |
| [CryptoGnome/Bybit-Futures-Bot](https://github.com/CryptoGnome/Bybit-Futures-Bot) | 120 | Dead 2022 liquidation-hunt. |

Search noise also produced: AWS course repos, Runescape gold bots, Amazon volume-by-price userscripts, crystal-symmetry “Wyckoff” (space groups), NiceHash ToS pastes. Filtered.

---

## Counts and how to read this

| Group | Listed | With stranger operational issues | With any PnL tag |
|---|---|---|---|
| A S/R · VP · MP | 23 | 2 (`py-market-profile` closed, `freqtrade/technical`) | 0 |
| B Order flow · LOB | 27 | 4 (visualizers + DeepLOB) | 0 |
| C SMC · ICT · Wyckoff | 33 | 1 (`smart-money-concepts`) | 0 trading |
| D BTC-corr · pairs | 11 | 0 crypto | 0 |
| E Futures practice | 48 | **~15** (table at top + OctoBot/bbgo/grid) | `[S]` only |
| F Multi-agent | 16 | nofx (dedup), others paper | Paper `[M]`/`[S]` |
| G Dead/scam | 19 | n/a (filter set) | `[M]` |
| **Unique-ish total** | **~110 after overlap** | **~15 that matter** | **1 research `[S]` edge** (funding) |

---

## What this means for the ideas in the query

1. **S/R, volume profile, market profile** — exist as **calculators**. Nobody is running a VP/POC bounce-vs-breakout bot with users. The one named VP futures bot has 1 star.
2. **Order book / footprint / tape** — exist as **charts and data SDKs**. The practiced “order flow” in OSS is hummingbot/ctubio **market making** (being *in* the book), not reading footprint for directional entries.
3. **SMC/ICT/FVG/liquidity** — one widely imported Python library, and it has a **documented lookahead bug**. Live SMC is TradingView + MT5 gold EAs. Crypto-futures SMC bots are toys.
4. **Wyckoff** — readers and 2026 AI wrappers. Weis wave exists in `srl-python-indicators`. No practiced Wyckoff futures bot.
5. **BTC-alt correlation / regime filter** — **not a GitHub genre**. Closest: a Bybit scalp bot that reads Binance MAs (`ryu878`), NFI volume pairlists, a 0★ README that says “BTC market filter”.
6. **Futures bots with practice** — NFI, passivbot, Haehnchen, OctoBot, bbgo grid, 51bitquant, ctubio MM, alpha-rptr. Strategy class: **grid, grind, dip-catch, MM**. Not the ideas in A–C.
7. **Trading teams** — LLM role-play. The only multi-human “team” with practice is NFI’s Discord + one grind strategy.
8. **Verified live PnL** — still **does not exist** on GitHub for these ideas. Funding-rate research is the only numbered edge in this slice.

If we implement S/R bounce-vs-breakout, VP, order-flow, SMC, or a BTC-regime filter, we are not competing with a crowded OSS field of working bots. We are competing with **nothing that has users** — and with the fact that the users who exist chose grind/grid instead.

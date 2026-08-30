# Forum mining: levels, bounce vs break, BTC-as-index, walls, averaging, own-account grind

**Date:** 2026-08-30  
**Question:** what do *real* retail and working traders write in public, independently, about five operational habits — and what is marketing dressed as consensus.  
**Method:** primary pages fetched and quoted. Independently recurring = same rule in ≥2 communities that do not copy each other. Marketing vs practitioner is flagged on every source.  
**Not covered this run (access blocked / 403–404):** live Reddit thread bodies (`old.reddit.com` search JSON 403; `site:reddit.com` queries returned no Reddit URLs). TradingView *comment threads* under ideas/scripts were not fetchable as comment text — only script descriptions and one RU idea body. Those gaps are marked. No invented Reddit usernames.

Related docs: `FINAL-PLAN-100k.md` (already cited Smart-Lab averaging), `FINAL-PLAN-SCALPING.md` (session window 16:00–19:00 MSK).

---

## How to read this memo

| Tag | Meaning |
|---|---|
| **PRACTITIONER** | Named commenter, old thread, dictionary that traders cite, or a script author admitting what the tool *cannot* do |
| **SCHOOL** | Canonical retail textbook (BabyPips School of Pipsology). Not a forum comment. Still the text most English retail copies |
| **BLOG / TG-FUNNEL** | Smart-Lab blog with Telegram CTA, affiliate, or “subscribe to my channel”. Rule may still be real if it matches independent sources |
| **VENDOR** | Prop-firm, broker, terminal vendor, ICT/SMC course site. Treat as marketing unless independently confirmed |
| **RESEARCH** | Cointelegraph Research / StackExchange accepted answers — documented, not a trading chat |

---

## 1. Recurring practitioner rules (≥2 independent communities)

### R1. Draw **zones**, not a single price line

**Rule:** Support/resistance is a band of congestion (bodies + wick extremes, or “edges of congestion”), not a horizontal through the spike high/low.

| Community | What they wrote | Source / tag |
|---|---|---|
| Smart-Lab dictionary (Elder-style, long-lived) | Levels should be drawn **not through extreme highs/lows**, but **along the edges of congestion areas**. Extremes are panic; the edge of the stall is where the crowd actually changed its mind. | [SL dictionary / support_level](https://smart-lab.ru/finansoviy-slovar/support_level) · **PRACTITIONER** (encyclopedia, 2011+ comments arguing how to draw it) |
| Smart-Lab 2025 blog (repeats the same rule) | «Ищите зоны, а не линии… диапазон 1.0975–1.1025 вместо 1.10000.» Senior TF (D1/W1/MN) first; ≥3 touches; round numbers. | [blog/1167607](https://smart-lab.ru/blog/1167607.php) · **BLOG / TG-FUNNEL** (`t.me/BirgewoySpekulant`) |
| BabyPips School | «Support and resistance levels are not exact numbers.» Treat them as **zones**. A close beyond a level can still be a test, not a break. Filter fakeouts by thinking in zones, not pips. | [What is Support and Resistance?](https://www.babypips.com/learn/forex/support-and-resistance) · **SCHOOL** |
| Elite Trader (2001, live tape) | Confirmation is **how trades print at the pivot**: speed, volume, bid/ask vs split — not the line itself. | [Will it bounce or break?](https://www.elitetrader.com/et/threads/will-it-bounce-or-break.1984/) Turok / Babak · **PRACTITIONER** |

**Independence check:** Elder/SL dictionary (RU equities, 2010s) ≠ BabyPips (FX school) ≠ Elite Trader tape readers (US stocks/futures, 2001). Same operational habit.

**Marketing version of the same idea:** “institutional gravity zones / order blocks drawn for you” (Trading Strategy Guides, SMC YouTube). The *zone* part is real; the “institutions left unfilled orders in this exact box” part is lore.

---

### R2. Bounce vs break: **react, don’t predict** — and don’t buy the first poke

**Rule:** At a known level you do not decide “bounce or break” in advance. You wait for a close / reaction. First break is often a fakeout. Conservative entry is **break → retest of the flipped level**. Aggressive entry is allowed but is a different, lower-quality bet.

| Community | What they wrote | Source / tag |
|---|---|---|
| Elite Trader | OP: “I either go long looking for a bounce or short looking for a break.” **Turok:** «I don't go looking for anything. If it breaks, I *(may)* go short. If it bounces I *(may)* go long. That's the difference between predicting and reacting. It will save you a ton of money.» **ktm:** let the stock tell you; ride the middle, don’t catch tops/bottoms. **armaniman:** already short into support / long into resistance; otherwise wait in the zone. | [ET 1984](https://www.elitetrader.com/et/threads/will-it-bounce-or-break.1984/) · **PRACTITIONER** |
| BabyPips School | Two plays: **Bounce** and **Break**. Bounce: wait for the bounce, don’t catch the falling knife. Break: aggressive = buy/sell the convincing pass; conservative = wait for pullback to the broken level. **All-caps warning:** *In forex, retests do NOT happen all the time. Price will sometimes leave you behind. Always use stops. Never hold on hope.* | [Trading the Lines](https://www.babypips.com/learn/forex/trading-the-lines) · **SCHOOL** (page blocked by Cloudflare this run; text from search extract + School canon) |
| BabyPips Forexpedia | Fakeouts: price moves just beyond S/R, traps breakout traders, reverses. Can happen **multiple times** before a real break. Genuine break may retest; if it doesn’t hold, it is a failed breakout. | [Breakout](https://www.babypips.com/forexpedia/breakout) · **SCHOOL** |
| Smart-Lab | Bounce in a range; break in a trend; “mix” = fade until the level actually gives, then reverse. Fakeout = poke then close back inside. **Novice error listed first:** «вход на пробой без ретеста». | [1167607](https://smart-lab.ru/blog/1167607.php), [1219227](https://smart-lab.ru/blog/1219227.php) · **BLOG / TG-FUNNEL** |
| Smart-Lab commenter (2011, dictionary) | Dondjon asks the same questions working traders still ask: *what is a break, what is a false break, where is the edge of congestion* — and calls the article «вода» until those are defined. | [support_level comments](https://smart-lab.ru/finansoviy-slovar/support_level) · **PRACTITIONER** |

**Independence check:** ET 2001 tape culture ≠ BabyPips FX school ≠ SL RU blogs. The shared operational rule is: **first print through the line is not a trade.**

**What is *not* independent consensus:** “first test = bounce, third test = break” as a probability table (Comparic / course blogs). Some traders use it as a heuristic; it is not a measured base rate in the threads above.

---

### R3. Higher timeframe owns the bias; intraday levels are noise without it

**Rule:** D1/H4 (or prior-day high/low + premarket) first. An H1 “strong resistance” sold against a fresh D1 bounce is how people get run over.

| Community | Paraphrase | Source / tag |
|---|---|---|
| Smart-Lab | «На более крупных таймфреймах уровни приобретают большую значимость.» D1 levels are “STRONG”; used as *cancel or take-profit*, not just entry. | [1115642](https://smart-lab.ru/blog/1115642.php); MAX OFF CAPITAL on dictionary page · **BLOG** / **TG** |
| BabyPips / School | Plot S/R on a line chart to drop the noise of wicks; weekly/daily matter more than the reflex of one candle. | School pages · **SCHOOL** |
| RU CScalp manuals | Book is 4/5 of the screen; BTC book is watched **in parallel** with the alt so you do not fade a local level while BTC is dumping. | [goodtrading.ru CScalp setup](https://goodtrading.ru/kak-nastroit-cscalp-podrobnyy-manual-so-skrinami/) · **VENDOR** (terminal how-to; describes actual desk layout) |

---

### R4. When trading alts, **read BTC first** — but do not treat correlation as a daytrade lock

**Rule (stress / directional):** Almost any alt is “BTC with a multiplier.” On a BTC dump, alts fall harder (thinner books, more leverage). A long alt into a weak BTC is double risk. Ten alts is not diversification — it is ten bets on BTC with different betas.

**Rule (intraday caveat from a commenter, not the blog):** On a *daytrade* horizon an alt can run against BTC long enough to blow a pairs/spread trade. “Вдолгую да — корреллирует, но какой в этом толк для трейдинга?”

| Community | Quote / paraphrase | Source / tag |
|---|---|---|
| Smart-Lab | «Большинство тех, кто торгует альткоины, смотрят на график самого альта… И упускают единственное, что реально движет этой монетой, — биткоин. Потому что почти любой альт — это, по сути, биткоин с усилителем.» On a 10% BTC drop, alts −20–30% is normal. «Лонг по альту на слабости биткоина — это двойной риск.» Author’s own follow-up: ten alts = ten bets on BTC. | [LiquidityScar, 2026-07-01](https://smart-lab.ru/blog/1322931.php) · **BLOG / TG-FUNNEL** (CTA to Telegram tracking) |
| Smart-Lab | «Торговать альткоины без анализа Bitcoin — всё равно что торговать отдельные акции, игнорируя движение всего индекса.» Panic → correlation → 1. Commenter **Андрей Аперов:** try trading alt-vs-BTC stat-arb and you lose your pants waiting for the spread to close; legs get ripped. Useful for *investing*, not always for *daytrading*. | [Investland, 2026-05-14](https://smart-lab.ru/blog/1303326.php) · **BLOG**; comment · **PRACTITIONER** |
| CScalp RU setup guides | Explicit second BTC book with “large volume” filters (e.g. 250 / 500) so the scalper sees BTC walls/flow while the alt book is the execution surface. | [goodtrading.ru](https://goodtrading.ru/kak-nastroit-cscalp-podrobnyy-manual-so-skrinami/) · **VENDOR** |

**Independence check:** SL crypto blogs 2026 + RU scalper terminal culture (CScalp has been the CIS crypto-scalp default for years). The *index* analogy is also how ET 2001 stock traders used NQ/ES vs single names (lassiter’s original question). Same habit, different market.

**Marketing version:** “BTC.D < 52% = deploy 20% into alts next week” listicles that invent Reddit usernames and upvote counts (LedgerMind-style recaps). **Not used here.** Dominance is a real *regime* tool; the exact 52% trigger is course-blog numerology.

---

### R5. Visible order-book **walls are not support** until they trade

**Rule:** A wall that relocates as price approaches is a *signal aimed at you*, not a floor. Real liquidity **prints**. Spoofed / whale walls **cancel or walk**. Landmark clusters of many small offers (round number) behave differently from one 30-BTC block that hops.

| Community | Quote / paraphrase | Source / tag |
|---|---|---|
| Bitcoin StackExchange (2013, Kraken, accepted) | **Murch:** Sell walls create the *impression* of supply so people sell in front of them. «The investor's goal is to move the market, not to actually sell… when the price gets too close, such walls often disappear or move to a higher price. Especially if you see the **same amount popping up at different prices**.» Separate type: many offers stacked at a landmark ($600) that **don’t move**. | [bitcoin.se/16918](https://bitcoin.stackexchange.com/questions/16918/what-is-the-strategy-behind-a-sell-wall) · **PRACTITIONER** (Murch) + later whale-playbook answers |
| Cointelegraph Research | Traders and *bots* use book density as S/R. Spoofers place cancellable size to make those bots trade the wrong way. Heuristic is adversarially broken. | [CT Research: spoofing](https://cointelegraph.com/research/crypto-market-spoofing-identifying-fake-orders-and-their-impact) · **RESEARCH** |
| Market-analysis (this repo, prior round) | CFTC cases on BTC futures spoofing; icebergs hide size. «Стена = сопротивление» is the exact heuristic spoofers feed. | `docs/market-analysis.md` § Кит 1 · **RESEARCH** |
| RU scalp terminals | Walls are *highlighted* as “крупный объём” so you *see* them — then you watch whether they get hit or pulled. MetaScalp/CScalp docs treat density as a **watch** item, not an auto-entry. | CScalp/MetaScalp manuals · **VENDOR** |

**Independence check:** 2013 BTC exchange users ≠ 2020s CT research ≠ CFTC enforcement. Same failure mode: trusting displayed size.

---

### R6. Averaging a **losing leveraged futures** position: consensus is **never** (as a rescue)

This is the cleanest multi-community rule in the set. People who defend averaging always add the same constraints: **no (or <1×) leverage, pre-planned grid, hard total risk, stop on the whole idea, own cash, many uncorrelated names.** None of those is “add to a 5× perp because it went −5%.”

| Community | Quote | Source / tag |
|---|---|---|
| Smart-Lab comments, 2017 | **Робот Бендер:** «Усреднение на плечах — это чистой воды дурость и в долгосроке слив 100%.» Averaging is a “grail” only with a fundamental edge **and** «при условии что вас не размажет на противоходе т.е. **без плечей**.» **Профуршетник:** «Данный принцип можно применять только на рынке акций и только на свои деньги, то есть неиспользуя плечи.» | [Мартин и усреднение](https://smart-lab.ru/blog/394144.php) · **PRACTITIONER** comments under a *pro-martingale* post |
| Smart-Lab, 2023 | **Ed Khan:** «Усреднение… Топ-1 причина слива начинающих и не очень.» Usual averaging has **no stop** → liquidation. The only “guaranteed not to blow” version: **total grid leverage < 1×**, on assets that move tens of percent *without* borrow. He admits BTC/ETH grid can reach ~1.5×; other coins **strictly <1×**. Caps return at ~20–25% year. | [951719](https://smart-lab.ru/blog/951719.php) · **BLOG** (algo TG) but the constraint is the point |
| Smart-Lab, 2025 | «Никогда не усредняйтесь в минусе.» No clear invalidation; size grows as you are being proven wrong. Add **only** in profit (pyramid). | [1170391](https://smart-lab.ru/blog/1170391.php) · **BLOG / TG-FUNNEL** (Whitelist risk-manager product) |
| US futures / prop pedagogy | Cost averaging on futures = doubling down / martingale. Works in a binary world; markets can go further than you can add. Eats margin that should be in a better trade. | [Topstep: cost averaging](https://www.topstep.com/blog/the-truth-about-cost-averaging) · **VENDOR** (prop), same rule |
| Minority **against** the consensus (do not confuse with consensus) | **Turbo Pascal** (same 2017 thread): he *likes* martingale for “psychological comfort”; deposit is a chip you clone and blow. Commenter: «в 80% случаев усреднение работает. в 20 — выносит счет нах.» Author: «Главное — удвоиться раньше слива.» | [394144](https://smart-lab.ru/blog/394144.php) · **PRACTITIONER** but this *is* the failure mode, not the rule |

**Independence check:** 2017 SL futures/equities comments ≠ 2023 SL crypto-grid author ≠ US prop blog. All three: **leverage + add-to-loser = eventual 100% wipe** if you stay long enough.

**What is *not* consensus:** “averaging is a professional tool if you cap the idea at 2–3%” ([1267212](https://smart-lab.ru/blog/1267212.php)) — **BLOG**, hedging language. Compatible with R6 only if that 2–3% is a **hard stop on the whole ladder**, which is then just a **scaled entry**, not “усреднение чтобы пересидеть.”

---

### R7. Volume Profile / POC: useful as a **map of where business was done**; useless as a mechanical signal (and most TV scripts are approximations)

| What users/authors actually admit | Source / tag |
|---|---|
| Pine has **no tick-at-price volume** on a normal chart. Profiles **distribute bar volume across the bar’s range** or pull lower-TF bars. Authors who are honest say: *estimate, not tape.* Buy/sell split from close-in-range is a proxy. | TradingView script pages: Precision Volume Profile [AxeAlgo], Zeiierman Order Flow Profiler, Trade Wzrd Tide — all **in the published description** · **PRACTITIONER** (authors warning their own users) |
| Official Pine docs: a volume profile that updates on the forming bar is **expected**; scripts that *relocate past events* are the misleading kind of repaint. | [TradingView Pine: Repainting](https://my.tradingview.com/pine-script-docs/concepts/repainting/) · **SCHOOL** |
| Elite Trader Market Profile lore (2008): **low volume** stops activity (trade it as S/R); **high volume** is an attractor, S/R **only on first touch**; if not rejected, expect to trade around it 1–2 hours; breakouts get **retested**. | [ET 3-2-1 / bthomas](https://www.elitetrader.com/et/threads/the-3-2-1-approach-a-simplified-method-for-trading-any-market.127338/) · **PRACTITIONER** (old MP floor culture) |
| Order-block scripts on TV: zones only after BOS; users report “not seeing OBs” until structure breaks; confluence-with-VP scripts hide non-confluent boxes. | Script docs (Tradenometry, Uncle_the_shooter) · **VENDOR**-adjacent |

**What failed (recurring, from authors not comments):** treating OHLC-estimated delta as real order flow; trading every POC touch; using visible-range VP as a backtestable level (it **moves when you zoom** — AxeAlgo says this explicitly).

**What “worked” in the sense practitioners keep the tool:** POC / HVN as *places to watch for reaction*, LVN as *air* (price travels fast). Same as R1 (zones of business), not a new edge.

---

## 2. Recurring failure modes

### F1. Buying the first break

- BabyPips: fakeouts are routine; price “just beyond” S/R to trap.  
- Smart-Lab 1167607: listed as **error #1**.  
- Elite Trader: predicting bounce-or-break *before* the print.  
- RU SMC/TV ideas (“Лондонский вынос”): London’s first break of Asia is **often** the stop-run, not the trend. This last one is **VENDOR/SMC** framing, but it describes the same trap as BabyPips fakeout.

**Operational translation:** no market order on the first tick through a line you drew. Close beyond the *zone*, or wait for the retest, or fade the failed break back into the range.

### F2. Trusting walls

- StackExchange: same size hops down the book → not a seller, a magnet for panic.  
- CT Research: bots that treat imbalance as S/R *are the prey*.  
- Prior repo audit: spoofing is the reason “wall = S/R” cannot be a model feature without a fill/cancel filter.

**Operational translation:** wall is a **hypothesis**. Confirm on the tape (absorbed vs pulled). Iceberg = small display, keeps refilling (opposite of spoof).

### F3. Averaging losers on futures / perps

Documented voices:

1. Bender / Профуршетник (SL 2017) — never with leverage.  
2. Ed Khan (SL 2023) — #1 blowup cause; only <1× grids.  
3. Whitelist (SL 2025) — averaging = no invalidation.  
4. Turbo Pascal thread math from the *other* side: 80% small wins, 20% account death — that **is** the martingale P&L shape (optional-stopping: many small pluses, one ruin).  
5. This repo’s Monte Carlo (`FINAL-PLAN-SCALPING.md`): 5× + add at −5% → **10.3% liquidation per trade**, median 12k ₽ from 100k in 6 months.

**Not a counter-example:** funds that “scale in” across 20 names without leverage. That is not what retail perps do.

### F4. Alt chart without BTC (and the opposite error)

- LiquidityScar: perfect alt TA, still dragged −20–30% by BTC.  
- Аперов: treating BTC-alt correlation as a *pairs trade* on a day horizon also blows up.  

**Both errors are real.** Filter: do not **initiate** an alt long into a breaking BTC; do not **assume** the alt must snap back to BTC this hour.

### F5. “Разгон” a 100k ₽ account with size instead of edge

See §5. This is the failure mode that connects F3 + leverage marketing.

---

## 3. What “professional team” retail actually mimics

There is **no documented CIS retail habit** of three humans sitting as “levels guy / BTC guy / news guy” on a 100k ₽ account. What *is* documented is **one person cloning a prop-desk layout** on 2–3 monitors.

| Role they are mimicking | What is on the glass | Source |
|---|---|---|
| **Levels / book** | CScalp/MetaScalp: **book is 4/5 of the workspace**, chart 1/5. Up to ~10 books on one screen. Densities highlighted as S/R *candidates*. | [goodtrading.ru CScalp](https://goodtrading.ru/kak-nastroit-cscalp-podrobnyy-manual-so-skrinami/); FSR CScalp docking docs · **VENDOR** describing users |
| **BTC / index** | Second book (or second monitor) on **BTC** with coarser “large volume” filters so you see whether the *index* is hitting or pulling size while you click the alt. | same CScalp manuals |
| **News / chat** | Smart-Lab workplace: one screen for **YouTube/news**, one for charts. CScalp ships a **Crypto chat** and news tab in-product. CPI/FOMC time is the actual “news desk” (16:30 MSK US prints). | [SL 425341](https://smart-lab.ru/blog/425341.php) **PRACTITIONER** (Timofey Martynov, 2–3 monitors, “можно обойтись”); CScalp product · **VENDOR** |

**Smart-Lab 425341 (2019, Martynov):** «Мой вердикт 2-3 минимум, 6 максимум… 3 монитора были явно лишние.» He mocks buying six screens *before* you can trade. That is the anti-marketing version of the same idea: the layout is for **attention split**, not for looking rich.

**What multi-agent GitHub “hedge fund roleplay” is:** marketing/research cosplay (TradingAgents), **not** what profitable CIS scalpers describe.

**What a system should copy from this (honest):** three *concurrent watches* with a veto: (1) pre-marked HTF zones, (2) BTC book/price regime, (3) scheduled news. One human already does this. Automating it is automating a **desk**, not hiring a team.

---

## 4. Session times for RU crypto daytraders (MSK)

Crypto is 24/7. **Activity is not.** RU scalp culture uses FX session clocks because that is when traditional risk desks and US news hit.

| Window (MSK) | What practitioners say happens | Source / tag |
|---|---|---|
| **03:00–10:00** | Asia: range, build liquidity, often flat. Scalp edges of the box or **don’t**. | TV idea [Indicator_Tony](https://ru.tradingview.com/chart/BTCUSDT/QXkmC1xY-urok-trejding-po-vremeni-vnutridnevnye-sessii/) · **BLOG** on TV (has a signal-bot CTA — discount the “strategy pack”, keep the clock) |
| **10:00–11:00** | London open: first impulse, often **breaks the Asian box**. | same; also TradersLifeCommunity TV ideas · **SMC / VENDOR** |
| **15:00–16:00** | NY open begins (winter/summer shifts ±1h with DST — authors usually ignore DST). | same |
| **16:00–16:30** | **Highest chaos.** «Многие профи ждут 15–30 минут после открытия, чтобы утих шум.» US data (CPI etc.) often **16:30**. | Indicator_Tony · **BLOG**; matches US equity “wait 15 minutes after the open” folklore (ET-adjacent) |
| **16:30–19:00** | London–NY overlap / “active US.” This is the window RU scalp plans already treat as **the** work block (`FINAL-PLAN-SCALPING.md`: 16:00–19:00). | Indicator_Tony; prior RU-scalp synthesis |
| **20:00–21:00** | Europe covers; fade/profit-take common. | Indicator_Tony |
| **23:00–01:00** | US close / positioning; then dead. | Indicator_Tony |
| **Overnight thin book** | Not a session — a **risk**. Holding 5× alts through Asia is how cascades happen. | prior plan docs + Ed Khan liquidity caveat |

**Marketing vs practitioner on sessions:**

- **ICT/SMC sites** (Hodie “kill zones”, “Smart Money most active 15:00–18:00”) sell a *narrative*. The clock overlaps the real liquidity clock; the “manipulation cycle” story is optional.  
- **Indicator_Tony** at least says: time is a **filter**, compute your own hit-rate per hour, news can void it, last month’s anomaly dies. That is closer to practitioner.  
- **Opening-range breakout of 10:00–11:00** is a real school strategy (equities ORB) ported to crypto — same fakeout problem as F1.

**Practical RU daytrader schedule that matches ≥2 sources:** prepare levels in the morning; optional London probe 10:00–12:00; **main risk-on 16:00–19:00 MSK**; flat or tiny into the US data print; do not invent edge at 04:00.

---

## 5. Attitude to “only own account, no prop, 100k ₽ → a big number”

### What is marketing

- **Prop-firm 2026 RU content** (Hash Hedge reviews, Bitcoin.com prop lists, “trade $100k without your own deposit”): challenge-fee businesses. They need you to believe 100k ₽ is *too small* so you buy a challenge. Pass-rate reality stays low; payouts are not a salary.  
- **«Разгон депозита» Telegram / broker blogs:** screenshots of 10k → 1M. JadeTrade-style articles (title checked; body 500 this run) and nikas.biz (2025-12-10): разгон = extreme volume-to-equity, only possible at 1:100–1:2000 kitchens. In regulated 1:20–1:50, a “comfortable” lot already wants **1.5–2M ₽**, not 100k.  
- **This repo’s earlier plans** that route 100k → millions **through prop/copy** are a *capital-access* argument, not a claim that prop is how serious traders “feel.” The user asked for **own-account** attitude: that path does **not** produce millions in months. Prior Monte Carlo: honest own-account + edge ≈ **×1.1–2 in 6 months**, not ×10.

### What practitioners actually write (own money)

| Voice | Attitude | Tag |
|---|---|---|
| Ed Khan (SL) | Averaging grids **without** leverage can live; they **rarely beat 20–25% year**. “Любителям иксов… не подойдёт.» | **BLOG**, but the return cap is the honest part |
| Turbo Pascal | Treats the deposit as a **chip** you blow and clone — only if you have *many* deposits. That is not a 100k ₽ life-savings plan. | **PRACTITIONER** (anti-pattern) |
| SL 1170391 | Friend at 10× ate 10% in a day; 1% daily-risk lived. Scale size **after** you survive, not to “reach the goal.” | **BLOG / TG** |
| Martynov workplace | Don’t buy a six-monitor prop-desk aesthetic before you have a process. | **PRACTITIONER** |
| RU “разгон” skeptics (broker/edu, 2025) | 100k ₽ without huge leverage **cannot** “разгон” by definition. High leverage is how the screenshots are made and how the accounts die. | **VENDOR**-adjacent, but anti-разгон |

### Consensus that survives marketing

1. **100k ₽ is a real account you can trade daily.** CIS crypto minimums allow it. That is not in dispute.  
2. **100k ₽ is not a bankroll for a “big goal” on a calendar.** At 1% risk and 3–8%/month *if* you have edge (the number RU scalp write-ups already use), you are in the **tens of percent per year** world, not the millions-in-months world.  
3. **Refusing prop does not change the math.** It only removes a fee-drain and a second set of rules. Own-account discipline is the same: stop instead of average, 1% not 10%, don’t hold 5× through Asia, trade the 16:00–19:00 window.  
4. **The respected RU attitude toward “only my money”** is: add from salary, compound slowly, treat 100k as **tuition + proof**, not as a rocket. The *disrespected* attitude is разгон and martingale-on-one-deposit.  
5. **“No prop, no funds” is a risk preference, not an edge.** It is compatible with everything in §1–2. It is incompatible with the goal “100k → 1M+ in 6 months.” Anyone selling both is marketing.

---

## 6. Source scorecard (what we could and could not mine)

| Source asked | What we got | Notes |
|---|---|---|
| Smart-Lab уровни / отскок / пробой | Yes — dictionary + 1167607, 1219227, 1115642 | Half are TG funnels repeating Elder/BabyPips. Comments on 394144 and support_level are the real ones. |
| Smart-Lab «биток тянет альты» | Yes — 1322931, 1303326 + comments | 2026 posts; one commenter usefully *limits* the rule to non-intraday. |
| Smart-Lab averaging | Yes — 394144 (the quote already in `FINAL-PLAN-100k.md` is **real**, Bender 2017-04-21), 951719, 1170391 | Confirmed: **never on leverage** is the comment consensus, not the OP of 394144. |
| Reddit r/Daytrading, r/FuturesTrading, r/algotrading, r/CryptoCurrency | **No thread bodies this run** | 403 / search suppression. Do not cite fake u/ usernames from SEO recaps. |
| TradingView ideas / scripts VP & OB | Script *descriptions* + one RU session idea | Authors themselves: OHLC estimate, visible-range VP moves, OB needs BOS. Comment sentiment not scraped. |
| Elite Trader | Yes — bounce/break 2001; MP 3-2-1 2008 | Brief, as requested. Gold standard of “react not predict.” |
| BabyPips | School pages (S/R, bounce/break, order block, fakeout) | Cloudflare blocked full HTML; extracts are School-canonical. Forum threads not pulled. |
| RU Telegram lore | Only where it **already leaked into articles** (CScalp manuals, SL blogs, TV ideas, разгон explainers) | No hearsay from unread channels. |

---

## 7. One-page takeaway for the system (no fantasies)

If the bot is allowed to copy **only** rules that showed up independently in ≥2 places:

1. Mark **HTF congestion zones** (not wick spikes, not a 5-minute line).  
2. **Do not enter on the first break.** Require close beyond the zone or a failed-break fade or a retest hold.  
3. **BTC is a hard filter** for alt direction on the *initiation* of risk; it is not a pairs-trade.  
4. **Walls are not levels** until they absorb. Track cancel/walk vs fill.  
5. **Code-forbid add-to-loser on perps.** Scaled entry *in profit* or a pre-declared <1× spot grid are different animals.  
6. One-trader “desk”: levels pane + BTC pane + news calendar. Not three AIs arguing.  
7. Trade RU daytime around **16:00–19:00 MSK**; treat 16:00–16:30 and scheduled US prints as **reduced size**.  
8. Own 100k ₽, no prop: **allowed and respectable**. The honest goal is survival + a few tens of percent a year *if* edge exists — not a million from the same pile.

Everything else (order-block religion, BTC.D magic numbers, “London sweep then NY reversal every day”, prop as the only path, разгон) is **marketing or unmeasured lore**.

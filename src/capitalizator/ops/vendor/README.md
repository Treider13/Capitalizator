# Desk visual engines (vendored)

Local copies. The console binds to localhost and does not load a CDN.
These files are the candle engine, slow-mo clock, and GPU book.

| file | engine | license | source |
| --- | --- | --- | --- |
| `lightweight-charts.standalone.production.js` | TradingView Lightweight Charts 4.2.3 | Apache-2.0 | https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js |
| `gsap.min.js` | GSAP 3.12.5 | GreenSock Standard License | https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js |
| `EasePack.min.js` | GSAP EasePack (SlowMo) 3.12.5 | GreenSock Standard License | https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/EasePack.min.js |
| `pixi.min.js` | PixiJS 7.4.2 | MIT | https://cdn.jsdelivr.net/npm/pixi.js@7.4.2/dist/pixi.min.js |

Served as `GET /vendor/<filename>` from the console. Unknown names and `..` return 404.
If a file is missing, the desk falls back to the inlined canvas/HTML painters.

Replay `0.25×` uses SlowMo on the playhead. Candle OHLC is still the vault tape — the engine does not invent bars.

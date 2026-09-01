"""Forum-pinned constants for contour B labels. Not A knobs. Not order size.

Each value is the public-discussion default we locked; the comment is the source.
"""

from __future__ import annotations

from decimal import Decimal

# RSI 14 (not 21): Wilder's original period and TA-Lib default. Crypto HTF (1h/4h)
# threads keep 14; 21 is the noisier 5m variant.
# https://stackoverflow.com/questions/20526414/relative-strength-index-in-python-pandas
# https://github.com/TA-Lib/ta-lib-python (RSI timeperiod=14)
RSI_PERIOD = 14
RSI_UNSTABLE_PERIOD = 100
RSI_HTF_TF = ("4h", "1h")

# FVG fill 100% (not 80%): price must sit inside the three-candle gap.
# joshyattridge/smart-money-concepts mitigates when price trades into the gap;
# 80% is the ICT "consequent encroachment" partial, not the library default.
# https://github.com/joshyattridge/smart-money-concepts
FVG_FILL_FRAC = Decimal("1.00")

# Sweep lookback 20 (not 50): Williams fractal + ICT equal-high scan on the last
# 20 candles. TradingView liquidity-sweep scripts default to 20; 50 is daily structure.
# https://www.tradingview.com/script/search/liquidity%20sweep/
SWEEP_LOOKBACK = 20
SWEEP_FRACTAL_N = 2

# Value Area 70% (not 68%): Steidlmayer Market Profile. 68% is a 1σ normal shortcut.
# https://github.com/bfolkens/py-market-profile (value_area_pct=0.70)
VALUE_AREA_FRAC = Decimal("0.70")

# GEX threshold > 1M: only when a chain exists. SpotGamma-style 1% dollar gamma
# is reported in millions; ignore noise below 1e6. No Deribit feed → label is None
# and context_ok skips GEX (does not vote).
# https://github.com/FlashAlpha-lab/gex-explained
GEX_THRESHOLD = Decimal("1000000")

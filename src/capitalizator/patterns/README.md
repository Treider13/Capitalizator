# patterns

Вход: закрытый бар и заранее построенная зона.
Выход: метка CAV (REJECT/THROUGH/COMPRESS/DRIFT/NOISE).
`w_now` / `w_rank` / `bar_quality` / `session_hour` — журнал касания, не голос и не размер.
Мёртвая K-линия (stagnant / illiquid) → CAV NOISE. Разрыв котировки режет окно ATR, не ставит NOISE.
`exam.hostile_exam` — протокол контура C, не вход.
Не делает: вход, SMC, торговлю по одной свече без книги, прогноз цены в жюри.
Ключи не читает.

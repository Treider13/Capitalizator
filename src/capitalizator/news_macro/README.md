# news_macro

Вход: `infra/calendars/macro.csv` (BLS/Fed, включая FOMC 9 Dec 2026 19:00Z EST); `unlocks.csv` (заголовок).
Выход: строки `news`; срез до `known_at` пустой. `Unlocks.team_today/tomorrow` — флаг скринера, не шорт.
`reaction_prior.csv` — заголовок, строк нет. n<5 → коэффициента нет. `opens_size` всегда false.
Не делает: скрейп TG/Tokenomist, «купи заголовок», коэффициент из блога как наша истина, выдуманные анлоки SOL.
Ключи не читает.

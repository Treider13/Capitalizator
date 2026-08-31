# news_macro

Вход: `infra/calendars/macro.csv` (даты BLS/Fed, две метки времени); `infra/calendars/unlocks.csv` (заголовок, строк нет).
Выход: строки `news`; срез до `known_at` пустой. `Unlocks.team_today/tomorrow` — флаг скринера, не шорт.
`reaction_prior.csv` — заголовок, строк нет. n<5 → коэффициента нет. `opens_size` всегда false.
Не делает: скрейп TG/Tokenomist, «купи заголовок», коэффициент из блога как наша истина, выдуманные анлоки SOL.
Ключи не читает.

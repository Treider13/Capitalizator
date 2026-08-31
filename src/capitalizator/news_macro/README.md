# news_macro

Вход: `infra/calendars/macro.csv` (даты BLS/Fed, две метки времени); `infra/calendars/unlocks.csv` (заголовок, строк нет).
Выход: строки `news`; срез до `known_at` пустой. `Unlocks.team_today/tomorrow` — флаг скринера, не шорт.
Не делает: скрейп TG/Tokenomist, «купи заголовок», коэффициент реакции с потолка, выдуманные анлоки SOL.
Ключи не читает.

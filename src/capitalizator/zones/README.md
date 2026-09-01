# zones

Вход: бары с `close_ts < t`, `infra/registry.yaml`.
Выход: `Zone` (prior_day_hl, swing) и `htf_bias`. Карта (`prior_day_hl` / `prior_session_hl` / `vp_hyp`) клеится с `working_tf`, чтобы CAV на 15m совпал с `zone.tf`. Источник уровня — method, не тег дня. `zone_id` = blake2s полей.
Не делает: ICT/FVG, зоны из будущего, вход в сделку.
Ключи не читает.

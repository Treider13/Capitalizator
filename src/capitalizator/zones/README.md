# zones

Вход: бары с `close_ts < t`, `infra/registry.yaml`.
Выход: `Zone` (prior_day_hl, swing) и `htf_bias`. `zone_id` = blake2s полей.
Не делает: ICT/FVG, зоны из будущего, вход в сделку.
Ключи не читает.

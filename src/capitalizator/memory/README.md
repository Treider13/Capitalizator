# memory

Вход: сделка и заранее построенные зоны; позже книга+лента, PRS, жест, BTC-метка.
Выход: `touch` pending → bounce / break / die; поля `tape_eaten`, `prs_y`, `gesture`, `btc_regime`. Журнал (не голос, не `rho_class_id`, не хеш): `w_now`, `w_rank`, `bar_quality`, `session_hour` (UTC час `ts`). `HashChain` — жест в цепи; подмена ломает verify. `episode` пустой.
Не делает: перерисовать прошлое, открыть сделку, крутить registry.yaml.
Ключи не читает.

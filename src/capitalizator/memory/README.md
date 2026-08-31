# memory

Вход: сделка и заранее построенные зоны; позже книга+лента, PRS, жест, BTC-метка.
Выход: `touch` pending → bounce / break / die; поля `tape_eaten`, `prs_y`, `gesture`, `btc_regime`.
Не делает: перерисовать прошлое, открыть сделку, крутить registry.yaml.
Ключи не читает.

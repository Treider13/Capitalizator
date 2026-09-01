# memory

Вход: сделка и заранее построенные зоны; позже книга+лента, PRS, жест, BTC-метка.
Выход: `touch` pending → bounce / break / die; поля `tape_eaten`, `prs_y`, `gesture`, `btc_regime`, `cav_label`, `jury`. `HashChain` — жест в цепи; подмена ломает verify. `episode` пустой. Склейка полей — `ops.contour.observe` только если контур on.
Не делает: перерисовать прошлое, открыть сделку, крутить registry.yaml.
Ключи не читает.

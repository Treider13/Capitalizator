# risk

Вход: плечо, стоп, эквити-счётчики, время, число позиций.
Выход: `Sizing.compute` / `Sizer.decide`; `Halts.state`; одно место `RiskEngine._open_position: Position | None`; `SessionWindow.allows` из `infra/time.yaml` + календарь.
`f5_target` = 1.2% только если `equity_source=main` и Г4. Сейчас `equity_source=none` → `None`, размер остаётся 1%. `phase.yaml` не пишет.
Не делает: average_in, ордер, 5x в Ф1, mainnet, 24ч-кат до CPI (это 2.11.7). Предложение отскока живёт в `exec`, не здесь.
Ключи не читает.

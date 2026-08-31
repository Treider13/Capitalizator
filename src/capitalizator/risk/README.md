# risk

Вход: плечо, стоп, эквити-счётчики, время, число позиций.
Выход: `Sizing.compute` / `Sizer.decide`; `Halts.state`; одно место `RiskEngine._open_position: Position | None`; `SessionWindow.allows` из `infra/time.yaml` + календарь.
Не делает: average_in, ордер, 5x в Ф1, стратегию отскока, mainnet, 24ч-кат до CPI (это 2.11.7).
Ключи не читает.

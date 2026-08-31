# whales

Вход: список claim. `WhalePit.load`: нет файла → пусто, не кошелёк. `known_at` обязателен. Поля `signal`/`weight`/`side` — отказ.
Выход: `whale_accepts()` и `WhalePit.accept()` всегда false; один claim `whale` — не вход.
Не делает: копировать один кошелёк, скрейп лидерборда, `hl_ingest.py`, теплокарта как магнит.
Ключи не читает.

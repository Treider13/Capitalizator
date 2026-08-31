# ops

`check_parquet_count`: путь к parquet и ожидаемое число строк. Код 0 только при точном совпадении.

`check_uptime`: span сделок ≥ `--hours` и нет тишины длиннее `--max-unmarked-gap-s` без события `gap`. `--universe` гоняет каждый символ из yaml. Не утверждает, что сутки на VPS уже сняты.

`daily_map_report`: касания, жесты, дыры, пинг. Токены «лонг / шорт / купи / продай / завтра» — ошибка, не совет.

`check_author_raw --min 20`: код 2, если сырых постов меньше порога. Не дописывает посты.

`check_author_parsed --min 50`: код 2, если разобранных (claims+horizon+known_at) меньше порога. Свободный текст без полей не считается.

`gates f0` / `f1` / `f2` / `f3` / `f4` / `f5kill`: сейчас код 2. Пустой журнал ≠ 80/40/100 и не чистый стакан. `infra/phase.yaml` не трогает. Пороги — `infra/gates.yaml` (лишний ключ — отказ).

`vault` / `knowledge` / `backup`: каталог как у Freqtrade `user_data` — знания (SQLite) отдельно от ленты (parquet). Секреты в бэкап не входят. Пустой журнал = 0 строк, не выдумка. `pack` отказывается при ключе в файле, сломанной хеш-цепочке, лишнем файле в `secrets/`. `restore` сверяет sha256 и число строк.

`console`: только GET, `127.0.0.1`. С ноута: `ssh -L 8082:127.0.0.1:8082 user@vps` и открыть страницу. POST ордера — 405. Советов «купи / лонг» в отчёте нет.

```
python -m capitalizator.ops.console --userdir ./user_data --init
python -m capitalizator.ops.backup pack --userdir ./user_data --dest ./cap-backup
python -m capitalizator.ops.console --userdir ./user_data --serve --port 8082
```

Не делает: торговлю, чтение ключей.

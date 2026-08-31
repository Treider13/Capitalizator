# База знаний и экран на ноуте

**Дата:** 2026-08-31 · Свой счёт. Ордеров отсюда нет.

Чужие рабочие столы (не копируем стратегии):

| Проект | Как хранят | Что берём |
|---|---|---|
| Freqtrade | `user_data/` отдельно от кода; сделки в `tradesv3.sqlite`; dry-run — другой файл; UI на `127.0.0.1:8080` | тот же раскол: код ≠ данные; SQLite едет на ноут целиком |
| Hummingbot | `data/` / `logs/` / `conf/` (ключи) порознь | бэкап данных без `conf` |
| Nautilus | parquet-каталог ленты ≠ состояние стратегии | наша лента уже parquet; знания — другая папка |

## Дерево

```
user_data/          ← VPS пишет, ноут копирует (rsync / pack)
  LAYOUT
  knowledge/desk.sqlite   зоны/жесты/эпизоды/отчёты, хеш-цепочка
  tape/                   parquet стакана и сделок
  reports/                вечерние карты текстом
  secrets/README.md       ключей здесь нет; каталог в бэкап не входит
```

Пустой `desk.sqlite` — норма на фазе 0. Ноль сделок не рисуем как плюс.

## Переезд

1. На VPS: `python -m capitalizator.ops.backup pack --userdir /var/lib/capitalizator --dest /tmp/cap-bak`  
2. `rsync` папки бэкапа на ноут (второй диск — раз в неделю).  
3. Новый сервер: `... backup restore --dest /tmp/cap-bak --userdir /var/lib/capitalizator`  
4. Ключ Bybit **новый** или новый IP в allowlist. Старый погасить.  
5. Сверка: те же `episodes` / `hash_links` / строки parquet, цепочка `verify` = true.

Дыры, которые тест ломает (перепроверка 31.08, третий проход):

- Секрет в файле / строке журнала; лишний файл в `secrets/`.
- Сломанная хеш-цепочка; `PRAGMA integrity_check` после snapshot.
- Лишний / пропавший файл; подмена sha256; непустой dest; dest — файл, не каталог.
- **Симлинк файла или каталога в слое** — `pathlib.rglob` умеет зайти в цель. Обход только `os.walk(followlinks=False)`. Слой-симлинк (`tape` → чужое) — отказ при `load_vault`.
- **FIFO / hardlink / не regular file** — чтение зависло бы или вклеило чужой inode. Отказ.
- **`../` в manifest** — путь не должен выходить из архива.
- **`--no-tape`** раньше не создавал `tape/` → `load_vault` падал. Теперь пустой каталог есть, счётчик parquet = 0.
- **Живой `shutil.copy` sqlite** — порча при открытой записи (документация SQLite / практика Freqtrade: не копировать файл на горячую). Пишем через `Connection.backup`. Счётчики берём **со снимка**, не с живого файла (иначе запись между `COUNT` и backup рвёт manifest).
- **Эпизод/отчёт вне цепочки** — тихий `UPDATE episodes` раньше проходил verify. Теперь строка пишется в той же `BEGIN IMMEDIATE`, что и звено; `verify_tables()` сверяет повтор со таблицами.
- **`verify`/`pack` не создают sqlite в источнике**, если его не было.
- **Parquet** — `mkstemp` + запись в fd + `replace` только если имя всё ещё наш inode. Предсказуемый `{pid}.tmp`-симлинк больше не затирает цель. Два писателя — `fcntl.LOCK_EX` + `O_NOFOLLOW` на `.lock` и перечит с диска. Счётчик — `metadata.num_rows` через fd, не `read()` всего часа.
- **`sqlite3.connect(path)` ходит по симлинку.** `desk.sqlite` → чужой файл консоль бы открыла. Отказ. Snapshot: serialize в память, байты в mkstemp, `replace` — цель старого симлинка не трогаем.
- **`shutil.copy2` / `copytree(symlinks=False)`** — документация Python: цель симлинка *вклеивается*. Копируем через `O_NOFOLLOW`. Restore только listed-файлы на staging, потом `rename`. Сбой не оставляет dest.
- Чтение отчёта / sha256 / parquet — тот же fd, не `path.open` (он следует за ссылкой).
- Консоль: нет поля `vps: false` (это была выдумка); без `LAYOUT` сервер **не** рисует хранилище; PUT/DELETE/PATCH = 405; симлинк в `tape/` не читает; исключение → 500 `error`, не traceback.

## Экран с ноута

На сервере (только localhost):

`python -m capitalizator.ops.console --userdir /var/lib/capitalizator --serve --port 8082`

На ноуте:

`ssh -L 8082:127.0.0.1:8082 user@vps`

Браузер: `http://127.0.0.1:8082` — режим, число сделок, цепочка, лента, отчёт дня. Кнопки входа нет. POST → 405. `0.0.0.0` консоль не слушает.

Это не сутки VPS и не живой пинг, пока железо не стоит. Страница честно пишет «сделок нет».

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
- **`sqlite3.connect(path)` ходит по симлинку.** Факт: после `close(fd)` можно подменить имя; `connect` открывает цель. Пишем через `/proc/self/fd/N` (тот же inode, что `O_NOFOLLOW`). Журнал SQLite остаётся у настоящего файла; повторный `connect(path)` видит те же байты. В stdlib нет `SQLITE_OPEN_NOFOLLOW`. Snapshot: serialize → запись через `dir_fd`.
- **`os.open(path, O_NOFOLLOW)` ходит в промежуточный dir-симлинк.** Факт: `dest/knowledge` → `outside`, `outside/desk.sqlite` есть, `is_symlink` False, `is_file` True; `Knowledge()` писал заголовок `SQLite format 3` в цель. Файл открываем только как `openat(parent_fd, name)`.
- **`os.replace(tmp, dest)` после проверки inode:** если *tmp* успели сменить на симлинк, rename **переносит ссылку** на dest. После rename сверяем inode; если dest — ссылка, `unlink` снимает имя, не цель.
- **`Path.write_text` / `read_text` ходят по ссылке.** LAYOUT и README пишем через `write_regular_text`.
- **`mkstemp(dir=parent)` + `os.replace(tmp, dest)` после подмены предка** пишут в цель симлинка (факт: `reports` → `outside`, `outside/nested` уже есть → файл в `outside`). Запись через `openat`/`dir_fd` + `renameat`: inode родителя держат до конца.
- **`Path.mkdir(parents=True)` ходит в симлинк-каталог.** Факт pathlib: `dest/reports` → `outside`, затем `dest/reports/nested.mkdir(parents=True)` создаёт `outside/nested`. Сам `nested` — обычный каталог, `parent.is_symlink()` после mkdir врёт. `ensure_real_parent` смотрит **каждого** предка (`abspath`, не `resolve` — тот прячет ссылку). Писатель ленты — `mkdir_real_parents` от корня `tape/`. `.lock` — только regular file (`O_NONBLOCK` + `S_ISREG`), не FIFO.
- **`shutil.copy2` / `copytree(symlinks=False)`** — документация Python: цель симлинка *вклеивается*. Копируем через `O_NOFOLLOW`. Restore только listed-файлы на staging, потом `rename`. Сбой не оставляет dest.
- **Staging `.{имя}.{pid}`** — то же семейство, что `{pid}.tmp`: имя угадывается (`/tmp/cap-bak`). `Path.exists()` ходит в симлинк. `shutil.rmtree` на 3.12 по dir-симлинку бросает OSError и цель не трогает — но чужой каталог с этим именем мы бы снесли. Теперь `tempfile.mkdtemp`; очистка `unlink` если имя — ссылка, не `rmtree` в цель.
- Чтение отчёта / sha256 / parquet — тот же fd, не `path.open` (он следует за ссылкой).
- Консоль: нет поля `vps: false` (это была выдумка); без `LAYOUT` сервер **не** рисует хранилище; PUT/DELETE/PATCH = 405; симлинк в `tape/` не читает; исключение → 500 `error`, не traceback.

## Экран с ноута

На сервере (только localhost):

`python -m capitalizator.ops.console --userdir /var/lib/capitalizator --serve --port 8082`

На ноуте:

`ssh -L 8082:127.0.0.1:8082 user@vps`

Браузер: `http://127.0.0.1:8082` — режим, число сделок, цепочка, лента, отчёт дня. Кнопки входа нет. POST → 405. `0.0.0.0` консоль не слушает.

Это не сутки VPS и не живой пинг, пока железо не стоит. Страница честно пишет «сделок нет».

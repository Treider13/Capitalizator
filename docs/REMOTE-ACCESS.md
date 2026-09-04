# Как подключиться к серверу и видеть всё (инструкция владельца)

С нуля (покупка VPS, install, ключ, learn → demo): [`NOVICE-START.md`](NOVICE-START.md).

Сервер: `91.229.105.226` (Амстердам, Ubuntu 26.04). Пользователи ОС: `root` (пароль — сменить) и
`trader` (для работы; ваши два публичных ключа уже добавлены в `/home/trader/.ssh/authorized_keys`).
Логин `dronpardon` — это панель HOSTKEY, не ОС.

## 1. Подключение

**Windows (PowerShell) / macOS / Linux:**
```bash
ssh -i ~/.ssh/id_rsa trader@91.229.105.226
```
Если ключ не подходит — по паролю `root` (`ssh root@91.229.105.226`), затем `su - trader`.

**Туннель к консоли** (консоль слушает только `127.0.0.1:8082` на сервере — наружу не открыта):
```bash
ssh -i ~/.ssh/id_rsa -L 8082:127.0.0.1:8082 trader@91.229.105.226
```
Держите это окно открытым и откройте в браузере **http://127.0.0.1:8082**.

## 2. Что где в консоли

| Адрес | Что видно |
|---|---|
| `http://127.0.0.1:8082/` | Стол: эквити/просадка/краны, позиции, очередь интентов, предупреждения, Свеча × Книга × Исход, жюри дня, входы заблокированы (почему), символы, режим, кнопка контура |
| `http://127.0.0.1:8082/ops` | **Управление**: блок входов и чужие позиции (принять / снять блок сигнера), команды столу (закрыть позиции, пауза/возобновить входы, снять кран, экзамен претендента, снять дрейф окна), риск-меню (все параметры с подсказками, потолки из phase.yaml), сессии (окна, размер, k·ATR, бюджет дня, дрейф, готовые к открытию), вселенная символов (применить предложение), ночь/экзамен/чемпион, журнал команд со статусами |
| `http://127.0.0.1:8082/settings` | **Настройки**: ключ Bybit (сюда вставлять API-ключ для реальных сделок), режим ключа, ключ LLM-провайдера и лимит, X/Reddit, Telegram-оповещения (сигнер шлёт при смене фактов: блок входов, кран, сторож; кнопка «Проверить Telegram»); список источников новостей с включателями и здоровьем |
| `http://127.0.0.1:8082/touch` | Последнее касание: все метки на русском |
| `http://127.0.0.1:8082/api/status` | Полный JSON-снимок |
| `http://127.0.0.1:8082/api/glossary` | Словарь кодов с подсказками |
| `/api/account`, `/api/queue`, `/api/paper`, `/api/risk`, `/api/commands`, `/api/settings`, `/api/sources`, `/api/sessions`, `/api/universe`, `/api/preview?touch_id=` | JSON для скриптов |

Все действия (режим, риск, команды, ключи) требуют токена подтверждения `ack_token`. В страницах
консоли он подставляется сам (скрытое поле формы / заголовок `X-Ack-Token`); вы отмечаете галочку
«Подтверждаю». Токен случайный, живёт пока живёт процесс консоли — чужая вкладка браузера или
сайт не смогут отправить команду от вашего имени (защита от CSRF и DNS-rebinding: проверяются
`Host`/`Origin`). Для скриптов: `curl -s http://127.0.0.1:8082/api/csrf` → `{"ack_token": ...}`,
далее заголовок `X-Ack-Token: <токен>`. Записи принимаются только с localhost (через туннель).

## 3. Куда вставить API-ключ Bybit

Вариант А — в консоли: `/settings` → группа «Биржа» → `bybit.api_key`, `bybit.api_secret`,
`bybit.mode` (`testnet` для демо, `live_sub` для реальных сделок) → «Сохранить группу».
Файл `/srv/capitalizator/userdir/secrets/bybit.json` создаётся автоматически с правами 0600, сигнер
подхватывает его на следующем цикле (≤ 1 с).

Вариант Б — файл вручную (на сервере, как `trader`):
```bash
cat > /srv/capitalizator/userdir/secrets/bybit.json <<'EOF'
{"api_key": "...", "api_secret": "...", "mode": "testnet"}
EOF
chmod 600 /srv/capitalizator/userdir/secrets/bybit.json
```
Ключ: сабаккаунт, права Read+Trade, **без Withdraw**, IP-whitelist = `91.229.105.226`.

Затем hello (проверка ключа, комиссий, инструментов, пробный ордер):
```bash
cd /srv/capitalizator/app/infra/deploy
docker compose run --rm signer python -m capitalizator.signer --userdir /data --hello --probe-order
```

## 4. Как включить реальные сделки (четыре замка, все нужны)

1. Ключ с `bybit.mode = live_sub` (п. 3).
2. `infra/phase.yaml` на сервере: `trading_mode: "live"` — правит человек после зелёного гейта
   `python -m capitalizator.ops.gates f4` (или с явной причиной оверрайда в консоли — она записывается).
3. В консоли кнопка `live` (токен подставляется сам); без записанного hello режим не включится.
4. Пары режимов: `demo ↔ testnet`, `live ↔ live_sub/live_main`.

## 5. Управление

```bash
cd /srv/capitalizator/app/infra/deploy
docker compose ps                         # состояние процессов
docker compose logs -f --tail 100 desk    # логи (recorder | desk | signer | intel | console | night)
docker compose restart signer             # перезапуск одного процесса
bash deploy.sh                            # (под trader) обновление кода и перезапуск изменившихся сервисов
```

Где данные: `/srv/capitalizator/userdir/knowledge/desk.sqlite` (журнал, память ОКО, настройки риска,
интенты, бумага, intel), `/srv/capitalizator/userdir/tape/` (лента: jsonl живой + parquet архив),
`/srv/capitalizator/userdir/secrets/` (только 0600), `/srv/capitalizator/backups/` (паки каждые 6 ч).

Контейнеры работают с минимумом прав: файловая система образа только на чтение, все capabilities
сброшены, `no-new-privileges`; `desk` и `night` вообще без сети; в образе нет ключей, тестов и
`.git`. Здоровье `desk`/`signer` = свежий heartbeat в SQLite (`docker compose ps` → `healthy`).
У `trader` нет sudo без пароля — для деплоя достаточно группы `docker`.

## 6. Безопасность после установки

- Сменить пароль `root`: `passwd`. Потом выключить парольный вход: `CAP_HARDEN=1 bash /root/install.sh`
  (только после того, как `ssh trader@…` по ключу точно работает).
- Ограничить SSH своим IP: `ufw allow from <ваш IP> to any port 22 proto tcp && ufw delete allow 22/tcp`.

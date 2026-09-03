# Развёртывание на VPS (один раз, потом только `deploy.sh`)

Всё живёт в `/srv/capitalizator`:

```
/srv/capitalizator/
├── app/        код (git clone), обновляется deploy.sh
├── userdir/    хранилище стола (vault): knowledge/ tape/ reports/ secrets/
├── backups/    паки knowledge раз в 6 часов (14 дней)
└── logs/
```

Процессы (Docker Compose, образ один, `python:3.12-slim`): `recorder` (сырой WS Bybit → parquet),
`desk` (стол 24/7), `signer` (единственный, кто видит ключ), `console` (только `127.0.0.1:8082`),
`night` (ночной контур в 00:30 UTC). Хост-Python (3.14) не используется.

## Шаг 0 — проверить биржу с сервера

```bash
curl -s -o /dev/null -w 'mainnet %{http_code} %{time_total}s\n' https://api.bybit.com/v5/market/time
curl -s -o /dev/null -w 'testnet %{http_code} %{time_total}s\n' https://api-testnet.bybit.com/v5/market/time
```
Ожидание `200`. Амстердам → ~0.2 с до движка (сам движок в Сингапуре).

## Шаг 1 — установка (root, один раз; повторный запуск безопасен)

```bash
curl -fsSL https://raw.githubusercontent.com/Treider13/Capitalizator/main/infra/deploy/install.sh -o install.sh
bash install.sh "ssh-ed25519 AAAA... ваш_публичный_ключ" <IP_вашего_ноутбука>
```
Что делает: пользователь `trader` (sudo, docker), UTC + chrony, UFW (22 только с вашего IP), fail2ban,
Docker, каталоги, клон репозитория. **Парольный вход не выключает**: сначала убедитесь, что
`ssh trader@<vps>` работает по ключу, затем `CAP_HARDEN=1 bash install.sh` — выключит пароль и root.

## Шаг 2 — ключи

Только у `signer`. Либо `infra/deploy/.env` (создаётся из `.env.example`, права 600):

```
BYBIT_API_KEY=...
BYBIT_API_SECRET=...
BYBIT_MODE=testnet        # testnet | live_sub | live_main
```
либо `/srv/capitalizator/userdir/secrets/bybit.json` с правами **0600**:
`{"api_key": "...", "api_secret": "...", "mode": "testnet"}`.

Ключ — сабаккаунт, Read+Trade, **без Withdraw**, IP-whitelist = IP сервера.

## Шаг 3 — запуск / обновление

```bash
sudo -u trader bash /srv/capitalizator/app/infra/deploy/deploy.sh
```
Собирает образ, поднимает стек. Повторный запуск = обновление кода (`git pull --ff-only`) и
перезапуск изменившихся сервисов. Данные не трогаются.

## Шаг 4 — консоль

```bash
ssh -L 8082:127.0.0.1:8082 trader@<vps>
# в браузере: http://127.0.0.1:8082
```
Наружу консоль не открывается (все команды принимаются только с localhost).

## Шаг 5 — hello на testnet

```bash
cd /srv/capitalizator/app/infra/deploy
docker compose run --rm signer python -m capitalizator.signer --userdir /data --hello --probe-order
```
Проверяет время, кошелёк, позиции, комиссии, инструменты, выставляет и снимает пробный ордер
(цена/объём — из `instruments-info`). Без зелёного hello режимы `demo`/`live` в консоли недоступны.

## Как включить реальную торговлю (четыре независимых замка)

1. Ключ с `mode: live_sub` (шаг 2).
2. `infra/phase.yaml`: `trading_mode: "live"` — пишет **человек** после зелёного гейта Ф4
   (`python -m capitalizator.ops.gates f4`). Бот файл не трогает.
3. В консоли режим `live` с подтверждением; без `trading_mode: "live"` консоль вернёт 409,
   если не указана явная причина оверрайда (она записывается).
4. Пара режимов: `demo ↔ testnet`, `live ↔ live_sub/live_main`. Иначе сигнер молчит.

## Бэкап

```bash
( crontab -l 2>/dev/null; echo '0 */6 * * * bash /srv/capitalizator/app/infra/deploy/backup.sh' ) | crontab -
```

## Диагностика

```bash
docker compose -f /srv/capitalizator/app/infra/deploy/compose.yml ps
docker compose -f /srv/capitalizator/app/infra/deploy/compose.yml logs -f --tail 100 desk
```
Статусы процессов и возраст ленты видны в консоли; `entries_blocked` показывает, почему сигнер
не отправляет входы (мёртвый пульс стола, разрыв сокета, расхождение сверки — снимается командой
«release_signer» в консоли).

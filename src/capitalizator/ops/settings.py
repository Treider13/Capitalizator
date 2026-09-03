"""Operator settings: secrets (keys, logins) and sources (URLs, accounts) — one place.

Secrets live in `<userdir>/secrets/settings.json`, mode 0600, on the VPS only; they are
never written to the knowledge DB, the journal, backups or logs. The console shows them
masked (`sk-…a1b2`). Sources (RSS URLs, Reddit subs, X accounts, Hyperliquid wallets)
are not secrets and live in knowledge meta `intel_sources` so every process can read
them. Every change appends a hash-chain link with the *field names* only.

Which processes read what:
  signer         bybit.api_key / api_secret / mode  (also honours gateway/keys.py env/file)
  intel-fetcher  x.bearer, reddit.client_id/secret, tradingview.session, sources
  intel-sandbox  llm.provider / model / api_key / monthly_budget_usd
  alerts         telegram.bot_token / chat_id
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.vault import Vault

SETTINGS_FILE = "settings.json"

# field → (group, label, secret?, hint)
FIELDS: dict[str, tuple[str, str, bool, str]] = {
    "bybit.api_key": ("Биржа", "API-ключ Bybit", True, "Сабаккаунт, права Read+Trade, без Withdraw, IP-whitelist = IP сервера."),
    "bybit.api_secret": ("Биржа", "API-секрет Bybit", True, "Хранится только в secrets/settings.json с правами 0600."),
    "bybit.mode": ("Биржа", "Режим ключа", False, "testnet | live_sub | live_main. demo работает только с testnet, live — только с live_*."),
    "llm.provider": ("Модель (ИИ-аналитик)", "Провайдер", False, "anthropic | openai | none. Модель читает новости/посты и извлекает утверждения; ключей биржи не видит."),
    "llm.model": ("Модель (ИИ-аналитик)", "Имя модели", False, "Например claude-sonnet-4-5 или gpt-4.1-mini. Ответ строго по JSON-схеме; совет о сделке невозможен."),
    "llm.api_key": ("Модель (ИИ-аналитик)", "Ключ провайдера", True, "Используется только процессом intel-sandbox."),
    "llm.monthly_budget_usd": ("Модель (ИИ-аналитик)", "Лимит расходов в месяц, $", False, "Процесс останавливает вызовы при превышении. 0 = без вызовов."),
    "x.bearer": ("Источники", "X (Twitter) API bearer", True, "Официальный API v2. Скрейпинг не используется. Пусто — источник выключен."),
    "reddit.client_id": ("Источники", "Reddit client id", False, "Приложение Reddit (script). Публичный JSON работает и без него, с лимитами."),
    "reddit.client_secret": ("Источники", "Reddit client secret", True, ""),
    "tradingview.session": ("Источники", "TradingView sessionid (свой аккаунт)", True, "Только собственный аккаунт: экспорт идей, без скрейпинга чужих страниц (ToS)."),
    "telegram.bot_token": ("Оповещения", "Telegram bot token", True, "Исходящие оповещения (инфо/критично). Чтение каналов запрещено каноном."),
    "telegram.chat_id": ("Оповещения", "Telegram chat id", False, "Куда слать. Тестовое сообщение — кнопкой «Проверить»."),
}

SOURCE_KINDS = ("rss", "reddit", "x_account", "hl_wallet", "tradingview_own")
FORBIDDEN_SOURCE_KINDS = ("telegram", "scrape", "tip")


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}…{value[-4:]}"


class Settings:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.path = vault.secrets / SETTINGS_FILE

    # --- secrets file (0600) ------------------------------------------------------------
    def load(self) -> dict[str, str]:
        if self.path.is_symlink() or not self.path.is_file():
            return {}
        st = self.path.stat()
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError(f"{self.path} must be 0600 (group/other readable)")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def save(self, values: Mapping[str, str]) -> None:
        self.vault.secrets.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.vault.secrets, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(values.items())), fh, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._sync_bybit_json(values)

    def _sync_bybit_json(self, values: Mapping[str, str]) -> None:
        """gateway/keys.py reads secrets/bybit.json; keep it in step (0600)."""
        key, secret = values.get("bybit.api_key"), values.get("bybit.api_secret")
        target = self.vault.secrets / "bybit.json"
        if not key or not secret:
            if target.exists():
                target.unlink()
            return
        body = {"api_key": key, "api_secret": secret, "mode": values.get("bybit.mode") or "testnet"}
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        os.chmod(target, 0o600)

    def update(
        self, changes: Mapping[str, str], *, knowledge: Knowledge | None = None, ack: bool
    ) -> dict[str, Any]:
        if not ack:
            raise ValueError("ack required")
        unknown = sorted(k for k in changes if k not in FIELDS)
        if unknown:
            raise ValueError(f"unknown settings: {unknown}")
        current = self.load()
        touched: list[str] = []
        for key, value in changes.items():
            value = str(value).strip()
            if key == "bybit.mode" and value and value not in {"testnet", "live_sub", "live_main"}:
                raise ValueError("bybit.mode must be testnet|live_sub|live_main")
            if key == "llm.provider" and value and value not in {"anthropic", "openai", "none"}:
                raise ValueError("llm.provider must be anthropic|openai|none")
            if key == "llm.monthly_budget_usd" and value:
                float(value)
            if value == "":
                if key in current:
                    del current[key]
                    touched.append(key)
                continue
            if current.get(key) != value:
                current[key] = value
                touched.append(key)
        self.save(current)
        if knowledge is not None and knowledge.available() and touched:
            knowledge.set_meta(
                "settings_changed",
                json.dumps({"at": datetime.now(tz=UTC).isoformat(), "fields": sorted(touched)}),
            )
        return {"changed": sorted(touched)}

    def view(self) -> list[dict[str, Any]]:
        """Masked view for the console: never the raw secret."""
        current = self.load()
        out = []
        for key, (group, label, secret, hint) in FIELDS.items():
            value = current.get(key, "")
            out.append(
                {
                    "key": key,
                    "group": group,
                    "label": label,
                    "secret": secret,
                    "hint": hint,
                    "set": bool(value),
                    "display": mask(value) if secret else value,
                }
            )
        return out

    def get(self, key: str) -> str | None:
        return self.load().get(key)


# --- sources (not secrets) -------------------------------------------------------------
def load_sources(knowledge: Knowledge) -> list[dict[str, Any]]:
    raw = knowledge.meta("intel_sources") if knowledge.available() else None
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def save_sources(knowledge: Knowledge, rows: list[dict[str, Any]]) -> None:
    knowledge.set_meta("intel_sources", json.dumps(rows, ensure_ascii=False, sort_keys=True))


def add_source(
    knowledge: Knowledge, *, kind: str, value: str, label: str = "", ack: bool
) -> dict[str, Any]:
    if not ack:
        raise ValueError("ack required")
    if kind in FORBIDDEN_SOURCE_KINDS:
        raise ValueError(f"source kind {kind!r} is forbidden by the canon")
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind {kind!r}")
    value = value.strip()
    if not value:
        raise ValueError("empty source")
    if kind == "rss":
        if not value.startswith("https://"):
            raise ValueError("rss url must be https")
        if "t.me/" in value:
            raise ValueError("telegram is forbidden as a source")
    if kind == "x_account":
        value = value.lstrip("@")
    if kind == "hl_wallet" and not (value.startswith("0x") and len(value) == 42):
        raise ValueError("hyperliquid wallet must be a 0x… address (42 chars)")
    rows = load_sources(knowledge)
    if any(r.get("kind") == kind and r.get("value") == value for r in rows):
        return {"added": False, "reason": "exists"}
    row = {
        "id": f"{kind}:{value}",
        "kind": kind,
        "value": value,
        "label": label.strip(),
        "enabled": True,
        "added_at": datetime.now(tz=UTC).isoformat(),
        "last_ok": None,
        "last_error": None,
    }
    rows.append(row)
    save_sources(knowledge, rows)
    return {"added": True, "source": row}


def set_source_enabled(knowledge: Knowledge, source_id: str, enabled: bool, *, ack: bool) -> bool:
    if not ack:
        raise ValueError("ack required")
    rows = load_sources(knowledge)
    hit = False
    for row in rows:
        if row.get("id") == source_id:
            row["enabled"] = bool(enabled)
            hit = True
    if hit:
        save_sources(knowledge, rows)
    return hit


def remove_source(knowledge: Knowledge, source_id: str, *, ack: bool) -> bool:
    if not ack:
        raise ValueError("ack required")
    rows = load_sources(knowledge)
    keep = [r for r in rows if r.get("id") != source_id]
    if len(keep) == len(rows):
        return False
    save_sources(knowledge, keep)
    return True


def default_sources() -> list[dict[str, str]]:
    """Public, ToS-clean starting set. The operator edits it in the console."""
    return [
        {"kind": "rss", "value": "https://www.coindesk.com/arc/outboundfeeds/rss/", "label": "CoinDesk"},
        {"kind": "rss", "value": "https://www.theblock.co/rss.xml", "label": "The Block"},
        {"kind": "rss", "value": "https://www.federalreserve.gov/feeds/press_all.xml", "label": "Federal Reserve"},
        {"kind": "rss", "value": "https://www.sec.gov/news/pressreleases.rss", "label": "SEC"},
        {"kind": "rss", "value": "https://announcements.bybit.com/en-US/rss/", "label": "Bybit announcements"},
        {"kind": "reddit", "value": "CryptoCurrency", "label": "r/CryptoCurrency"},
        {"kind": "reddit", "value": "Bitcoin", "label": "r/Bitcoin"},
    ]


def ensure_default_sources(knowledge: Knowledge) -> int:
    if load_sources(knowledge):
        return 0
    n = 0
    for row in default_sources():
        out = add_source(knowledge, kind=row["kind"], value=row["value"], label=row["label"], ack=True)
        n += int(bool(out.get("added")))
    return n


def secrets_path(vault: Vault) -> Path:
    return vault.secrets / SETTINGS_FILE

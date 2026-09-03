"""Настройки: ключи в secrets/settings.json (0600, маска в UI), источники в knowledge,
запреты канона (Telegram/скрейпинг), синхронизация bybit.json для сигнера."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from capitalizator.gateway.keys import load_keys
from capitalizator.ops.console import ConsoleApp, _api_get
from capitalizator.ops.i18n_ru import glossary, hint, ru
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.settings import Settings, add_source, ensure_default_sources, load_sources
from capitalizator.ops.settings_page import render_settings_html
from capitalizator.ops.vault import init_vault


def test_secrets_are_0600_masked_and_feed_the_signer(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    app = ConsoleApp(vault)
    with pytest.raises(ValueError, match="ack"):
        app.settings_post("/api/settings", {"llm.provider": "anthropic"}, ack=False)
    out = app.settings_post(
        "/api/settings",
        {"bybit.api_key": "KEY123456789", "bybit.api_secret": "SECRETXYZ987", "bybit.mode": "testnet",
         "llm.provider": "anthropic", "llm.model": "claude-sonnet-4-5", "llm.api_key": "sk-ant-abcdef0123456789"},
        ack=True,
    )
    assert set(out["changed"]) >= {"bybit.api_key", "llm.api_key"}
    path = vault.secrets / "settings.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = json.loads(path.read_text())
    assert raw["bybit.api_secret"] == "SECRETXYZ987"
    # the console never shows the raw secret
    view = {f["key"]: f for f in _api_get(vault, "/api/settings", {})["fields"]}
    assert view["bybit.api_secret"]["display"] not in ("SECRETXYZ987",) and "…" in view["bybit.api_secret"]["display"]
    assert view["llm.model"]["display"] == "claude-sonnet-4-5"
    page = render_settings_html(Settings(vault).view(), [])
    assert "SECRETXYZ987" not in page and "sk-ant-abcdef0123456789" not in page
    assert "Подтверждение" in page and "не задано" in page
    # gateway/keys.py reads the synced bybit.json
    keys = load_keys(vault, env={})
    assert keys is not None and keys.api_key == "KEY123456789" and keys.mode == "testnet"
    # empty value deletes; bad mode refused
    with pytest.raises(ValueError, match="bybit.mode"):
        app.settings_post("/api/settings", {"bybit.mode": "mainnet"}, ack=True)
    app.settings_post("/api/settings", {"bybit.api_key": "", "bybit.api_secret": ""}, ack=True)
    assert load_keys(vault, env={}) is None
    # knowledge records field names only
    kn = open_knowledge(vault)
    changed = json.loads(kn.meta("settings_changed"))
    assert "bybit.api_key" in changed["fields"] and "KEY123456789" not in json.dumps(changed)
    kn.close()
    # world-readable file is refused
    os.chmod(path, 0o644)
    with pytest.raises(ValueError, match="0600"):
        Settings(vault).load()


def test_sources_respect_the_canon(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    assert ensure_default_sources(kn) >= 5
    with pytest.raises(ValueError, match="forbidden"):
        add_source(kn, kind="telegram", value="https://t.me/x", ack=True)
    with pytest.raises(ValueError, match="telegram"):
        add_source(kn, kind="rss", value="https://t.me/s/channel", ack=True)
    with pytest.raises(ValueError, match="https"):
        add_source(kn, kind="rss", value="http://example.com/feed", ack=True)
    with pytest.raises(ValueError, match="0x"):
        add_source(kn, kind="hl_wallet", value="notawallet", ack=True)
    out = add_source(kn, kind="x_account", value="@someone", label="тест", ack=True)
    assert out["added"] and out["source"]["value"] == "someone"
    assert add_source(kn, kind="x_account", value="someone", ack=True)["added"] is False
    app = ConsoleApp(vault)
    sid = out["source"]["id"]
    assert app.settings_post("/api/sources", {"action": "disable", "id": sid}, ack=True)["updated"]
    assert next(s for s in load_sources(kn) if s["id"] == sid)["enabled"] is False
    assert app.settings_post("/api/sources", {"action": "remove", "id": sid}, ack=True)["removed"]
    kn.close()


def test_russian_glossary_covers_desk_codes() -> None:
    assert ru("DEFEND").startswith("ЗАЩИТА") and "(DEFEND)" in ru("DEFEND")
    assert "снятые заявки" in hint("DEFEND")
    assert ru("no_such_code") == "no_such_code" and hint("no_such_code") == ""
    codes = {g["code"] for g in glossary()}
    for c in ("ACCORD", "SPLIT", "VETO", "SILENCE", "REJECT", "THROUGH", "SPOOF", "ABSORB",
              "BUILD_LONG", "RANGE", "TRANSITION", "bounce", "spring", "no_gateway", "reconcile_mismatch"):
        assert c in codes
    for g in glossary():  # hints describe facts, never advise
        low = (g["name"] + " " + g["hint"]).lower()
        assert "купи" not in low and "продай" not in low


def test_glossary_endpoint_passes_the_advice_filter() -> None:
    import json

    from capitalizator.ops.daily_map_report import contains_advice

    assert not contains_advice(json.dumps(glossary(), ensure_ascii=False))


def test_intel_is_runnable_as_a_module() -> None:
    """`python -m capitalizator.intel` must exist (the VPS service restart-looped without it)."""
    from pathlib import Path as _P

    import capitalizator.intel as pkg

    assert (_P(pkg.__file__).parent / "__main__.py").is_file()

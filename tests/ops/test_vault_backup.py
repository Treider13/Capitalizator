"""Vault layers + pack/restore holes. Empty is honest. Secrets never travel."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.ops.backup import BackupError, pack, restore, verify_backup
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import VaultError, init_vault, load_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent


def _event() -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=datetime(2026, 8, 30, 13, 30, 1, tzinfo=UTC),
        recv_ts=datetime(2026, 8, 30, 13, 30, 1, 1, tzinfo=UTC),
        seq=1,
        payload={"px": "65000", "qty": "0.001", "side": "buy"},
    )


def test_empty_vault_pack_restore_stays_empty(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        assert knowledge.counts() == {"hash_links": 0, "episodes": 0, "reports": 0}
        assert knowledge.verify_chain()
    finally:
        knowledge.close()
    backup = tmp_path / "bak"
    manifest = pack(vault, backup)
    assert manifest["counts"]["episodes"] == 0
    assert manifest["counts"]["parquet_rows"] == 0
    assert manifest["secrets_excluded"] is True
    verify_backup(backup)
    dest = tmp_path / "moved"
    restored = restore(backup, dest)
    kn = open_knowledge(restored)
    try:
        assert kn.counts()["episodes"] == 0
        assert kn.verify_chain()
    finally:
        kn.close()
    assert not any(
        p.name not in {"README.md", ".gitkeep"} for p in restored.secrets.iterdir()
    )


def test_roundtrip_keeps_rows_and_chain(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    try:
        kn.append_link("zone|DEFEND")
        kn.append_episode(
            {
                "trade_id": "e1",
                "mode": "demo",
                "zone_id": "z1",
                "gesture": "DEFEND",
                "fill": datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
                "slip": "0",
                "fees": "20",
                "r": "1.5",
            }
        )
        kn.save_report(day="2026-08-30", kind="map", body="# Карта 2026-08-30\n\nКасаний нет.\n")
    finally:
        kn.close()
    ParquetSink(vault.tape).write(_event())
    backup = tmp_path / "bak"
    manifest = pack(vault, backup)
    assert manifest["counts"]["episodes"] == 1
    assert manifest["counts"]["hash_links"] == 3
    assert manifest["counts"]["reports"] == 1
    assert manifest["counts"]["parquet_rows"] == 1
    dest = tmp_path / "moved"
    restored = restore(backup, dest)
    kn2 = open_knowledge(restored)
    try:
        assert kn2.counts() == {"hash_links": 3, "episodes": 1, "reports": 1}
        assert kn2.verify_ok()
        assert kn2.episodes()[0]["r"] == "1.5"
        assert kn2.report(day="2026-08-30") is not None
    finally:
        kn2.close()


def test_secret_file_blocks_pack(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    (vault.knowledge / "note.txt").write_text("BYBIT" + "_API_" + "KEY=abc\n", encoding="utf-8")
    with pytest.raises(BackupError, match="unexpected|secret"):
        pack(vault, tmp_path / "bak")


def test_pack_does_not_create_source_db(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    assert not vault.db_path.is_file()
    pack(vault, tmp_path / "bak")
    assert not vault.db_path.is_file()
    verify_backup(tmp_path / "bak")


def test_no_tape_pack_still_verifies(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    manifest = pack(vault, tmp_path / "bak", with_tape=False)
    assert "tape" not in manifest["layers"]
    assert manifest["counts"]["parquet_rows"] == 0
    verify_backup(tmp_path / "bak")


def test_symlink_in_tape_is_refused(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    target = tmp_path / "outside.txt"
    target.write_text("secret-target\n", encoding="utf-8")
    (vault.tape / "leak.parquet").symlink_to(target)
    with pytest.raises(BackupError, match="symlink"):
        pack(vault, tmp_path / "bak")


def test_manifest_path_escape_is_refused(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    backup = tmp_path / "bak"
    pack(vault, backup)
    evil = tmp_path / "evil.txt"
    evil.write_text("x", encoding="utf-8")
    manifest_path = backup / "manifest.json"
    import json

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["files"]["../evil.txt"] = {"sha256": "00", "bytes": 1}
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(BackupError, match="unsafe|escapes|sha256"):
        verify_backup(backup)


def test_restored_db_integrity_ok(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.append_link("zone|DEFEND")
    kn.close()
    backup = tmp_path / "bak"
    pack(vault, backup)
    restored = restore(backup, tmp_path / "moved")
    kn2 = open_knowledge(restored, create=False)
    try:
        assert kn2.integrity_ok()
        assert kn2.verify_ok()
        assert kn2.counts()["hash_links"] == 1
    finally:
        kn2.close()


def test_secrets_dir_extra_file_blocks_pack(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    (vault.secrets / "key.age").write_text("nope", encoding="utf-8")
    with pytest.raises(BackupError, match="secrets"):
        pack(vault, tmp_path / "bak")


def test_secret_in_episode_blocks_pack(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    try:
        kn.append_episode(
            {
                "trade_id": "e1",
                "mode": "demo",
                "zone_id": "z1",
                "gesture": "ghp_leak",
                "fill": "2026-08-30T14:00:00+00:00",
                "slip": "0",
                "fees": "0",
                "r": "0",
            }
        )
    finally:
        kn.close()
    with pytest.raises(BackupError, match="secret"):
        pack(vault, tmp_path / "bak")


def test_broken_chain_blocks_pack(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    try:
        kn.append_link("a")
        kn.append_link("b")
        kn._cx.execute("UPDATE hash_links SET payload = 'tamper' WHERE id = 1")
        kn._cx.commit()
        assert kn.verify_chain() is False
    finally:
        kn.close()
    with pytest.raises(BackupError, match="hash chain"):
        pack(vault, tmp_path / "bak")


def test_tampered_backup_file_is_rejected(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    backup = tmp_path / "bak"
    pack(vault, backup)
    (backup / "reports" / "extra.txt").write_text("hole", encoding="utf-8")
    with pytest.raises(BackupError, match="extra"):
        verify_backup(backup)


def test_missing_listed_file_is_rejected(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.save_report(day="2026-08-30", kind="map", body="Касаний нет.\n")
    kn.close()
    (vault.reports / "keep.txt").write_text("x", encoding="utf-8")
    backup = tmp_path / "bak"
    pack(vault, backup)
    listed = next(p for p in (backup / "reports").iterdir() if p.is_file())
    listed.unlink()
    with pytest.raises(BackupError, match="missing"):
        verify_backup(backup)


def test_sha256_mismatch_is_rejected(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    (vault.reports / "keep.txt").write_text("x", encoding="utf-8")
    backup = tmp_path / "bak"
    pack(vault, backup)
    target = backup / "reports" / "keep.txt"
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(BackupError, match="sha256"):
        verify_backup(backup)


def test_nonempty_dest_restore_refused(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    backup = tmp_path / "bak"
    pack(vault, backup)
    dest = tmp_path / "moved"
    dest.mkdir()
    (dest / "old").write_text("x", encoding="utf-8")
    with pytest.raises(BackupError, match="not empty"):
        restore(backup, dest)


def test_load_requires_layout(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not a vault"):
        load_vault(tmp_path / "nope")


def test_advice_report_rejected(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    try:
        with pytest.raises(ValueError, match="advise"):
            kn.save_report(day="2026-08-30", kind="map", body="купи BTC\n")
    finally:
        kn.close()


def test_tampered_episode_breaks_tables_and_pack(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    try:
        kn.append_episode(
            {
                "trade_id": "e1",
                "mode": "demo",
                "zone_id": "z1",
                "gesture": "DEFEND",
                "fill": "2026-08-30T14:00:00+00:00",
                "slip": "0",
                "fees": "0",
                "r": "1.5",
            }
        )
        assert kn.verify_ok()
        kn._cx.execute("UPDATE episodes SET r = '99' WHERE trade_id = 'e1'")
        kn._cx.commit()
        assert kn.verify_chain() is True
        assert kn.verify_tables() is False
    finally:
        kn.close()
    with pytest.raises(BackupError, match="hash chain"):
        pack(vault, tmp_path / "bak")


def test_fifo_in_tape_is_refused(tmp_path: Path) -> None:
    import os

    vault = init_vault(tmp_path / "desk")
    os.mkfifo(vault.tape / "x.parquet")
    with pytest.raises(BackupError, match="regular file"):
        pack(vault, tmp_path / "bak")


def test_dir_symlink_in_tape_is_refused(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "stolen.parquet").write_bytes(b"not-a-key-but-outside")
    (vault.tape / "evil").symlink_to(outside)
    with pytest.raises(BackupError, match="symlink"):
        pack(vault, tmp_path / "bak")


def test_layer_symlink_is_refused(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    vault.tape.rmdir()
    vault.tape.symlink_to(tmp_path / "desk" / "reports")
    with pytest.raises(VaultError, match="symlink"):
        load_vault(vault.root)


def test_pack_dest_file_is_refused(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    dest = tmp_path / "bak"
    dest.write_text("nope", encoding="utf-8")
    with pytest.raises(BackupError, match="not a directory"):
        pack(vault, dest)


def test_hardlink_in_reports_is_refused(tmp_path: Path) -> None:
    import os

    vault = init_vault(tmp_path / "desk")
    outside = tmp_path / "outside.txt"
    outside.write_text("plain", encoding="utf-8")
    os.link(outside, vault.reports / "keep.txt")
    with pytest.raises(BackupError, match="hardlink"):
        pack(vault, tmp_path / "bak")


def test_failed_restore_does_not_create_dest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import capitalizator.ops.backup as bak

    vault = init_vault(tmp_path / "desk")
    (vault.reports / "keep.txt").write_text("x", encoding="utf-8")
    backup = tmp_path / "bak"
    pack(vault, backup)
    dest = tmp_path / "moved"
    real = bak.copy_regular

    def boom(src: Path, target: Path) -> None:
        if target.name == "keep.txt":
            raise OSError("disk")
        real(src, target)

    monkeypatch.setattr(bak, "copy_regular", boom)
    with pytest.raises(OSError, match="disk"):
        restore(backup, dest)
    assert not dest.exists()
    leftovers = list(dest.parent.glob(f".{dest.name}.*.restore"))
    assert leftovers == []


def test_knowledge_refuses_symlink_db(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import Knowledge

    real = tmp_path / "real.sqlite"
    Knowledge(real).close()
    link = tmp_path / "desk.sqlite"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        Knowledge(link)


def test_snapshot_does_not_write_through_symlink(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import Knowledge

    src = tmp_path / "src.sqlite"
    kn = Knowledge(src)
    kn.append_link("zone|DEFEND")
    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    dest = tmp_path / "out.sqlite"
    dest.symlink_to(secret)
    kn.snapshot_to(dest)
    kn.close()
    assert secret.read_bytes() == b"KEYMATERIAL"
    assert dest.is_symlink() is False
    kn2 = Knowledge(dest, create=False)
    try:
        assert kn2.counts()["hash_links"] == 1
        assert kn2.verify_ok()
    finally:
        kn2.close()


def test_write_regular_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    from capitalizator.ops.vault import write_regular_text

    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    dest = tmp_path / "LAYOUT"
    dest.symlink_to(secret)
    write_regular_text(dest, "1\n")
    assert secret.read_bytes() == b"KEYMATERIAL"
    assert dest.is_symlink() is False
    assert dest.read_text(encoding="utf-8") == "1\n"


def test_replace_if_same_unlinks_result_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from capitalizator.ops.vault import replace_if_same

    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    tmp = tmp_path / "tmp"
    tmp.write_bytes(b"data")
    dest = tmp_path / "dest"
    created = tmp.lstat()
    real = os.replace

    def sneaky(src: Path, dst: Path) -> None:
        real(src, dst)
        Path(dst).unlink()
        Path(dst).symlink_to(secret)

    monkeypatch.setattr(os, "replace", sneaky)
    with pytest.raises(VaultError, match="unexpected inode"):
        replace_if_same(tmp, dest, created)
    assert secret.read_bytes() == b"KEYMATERIAL"
    assert dest.exists() is False


def test_init_refuses_layout_symlink(tmp_path: Path) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    (root / "LAYOUT").symlink_to(secret)
    with pytest.raises(VaultError, match="symlink"):
        init_vault(root)
    assert secret.read_bytes() == b"KEYMATERIAL"


def test_lock_file_is_not_packed(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    ParquetSink(vault.tape).write(_event())
    assert list(vault.tape.rglob("*.lock"))
    manifest = pack(vault, tmp_path / "bak")
    assert manifest["counts"]["parquet_rows"] == 1
    listed = " ".join(manifest["files"])
    assert ".lock" not in listed

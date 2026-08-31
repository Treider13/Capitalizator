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


def test_create_false_does_not_init_empty_sqlite(tmp_path: Path) -> None:
    """Fact: SQLite treats a 0-byte file as a new db and writes a header.

    Knowledge(create=False) used to executescript(SCHEMA) on that inode.
    pack then snapshotted the invented db and left 32KiB in the source vault.
    """
    from capitalizator.ops.knowledge import Knowledge

    empty = tmp_path / "desk.sqlite"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty knowledge db"):
        Knowledge(empty, create=False)
    assert empty.stat().st_size == 0
    assert empty.read_bytes() == b""


def test_pack_empty_sqlite_does_not_write_source(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    vault.db_path.write_bytes(b"")
    with pytest.raises(BackupError, match="empty knowledge db"):
        pack(vault, tmp_path / "bak")
    assert vault.db_path.stat().st_size == 0
    assert vault.db_path.read_bytes() == b""


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


def test_copy_regular_refuses_hardlink_on_open_fd(tmp_path: Path) -> None:
    """Walk already refuses nlink>1. Copy must refuse on the fd it actually reads:

    after the walk, a hardlink onto a key would otherwise be packed as bytes.
    """
    import os

    from capitalizator.ops.vault import copy_regular

    secret = tmp_path / "secret"
    secret.write_text("KEYMATERIAL", encoding="utf-8")
    src = tmp_path / "src.txt"
    os.link(secret, src)
    with pytest.raises(VaultError, match="hardlink"):
        copy_regular(src, tmp_path / "dest" / "keep.txt")
    assert secret.read_text(encoding="utf-8") == "KEYMATERIAL"


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


def test_pack_does_not_touch_predictable_pid_staging(tmp_path: Path) -> None:
    import os

    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    dest = tmp_path / "bak"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("secret", encoding="utf-8")
    planted = dest.parent / f".{dest.name}.{os.getpid()}.partial"
    planted.symlink_to(outside)
    pack(vault, dest)
    assert dest.is_dir()
    assert planted.is_symlink()
    assert (outside / "keep").read_text(encoding="utf-8") == "secret"


def test_remove_staging_does_not_rmtree_through_swapped_parent(tmp_path: Path) -> None:
    """Fact: after dest.parent is swapped for a symlink, Path.rmtree follows
    and deletes the victim tree. Cleanup must use the parent dir_fd or refuse."""
    from capitalizator.ops.backup import _make_staging, _remove_staging

    parent = tmp_path / "cap-bak"
    parent.mkdir()
    staging = _make_staging(parent, "out", suffix=".partial")
    (staging / "LAYOUT").write_text("1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / staging.name
    victim.mkdir()
    (victim / "keep").write_text("VICTIM", encoding="utf-8")
    parent.rename(tmp_path / "cap-bak.real")
    (tmp_path / "cap-bak").symlink_to(outside)
    _remove_staging(staging)
    assert (victim / "keep").read_text(encoding="utf-8") == "VICTIM"


def test_pack_parent_swap_does_not_delete_victim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fact: Path.rename and shutil.rmtree follow a swapped dest.parent.

    Hold the parent inode; on failure remove_tree_at that fd, not the Path.
    """
    import capitalizator.ops.backup as bak

    vault = init_vault(tmp_path / "desk")
    dest_parent = tmp_path / "bak-parent"
    dest_parent.mkdir()
    dest = dest_parent / "out"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_mkdir = bak._mkdir_layers_at

    def swap_after(parent_fd: int, staging_name: str) -> None:
        real_mkdir(parent_fd, staging_name)
        planted = outside / staging_name
        planted.mkdir()
        (planted / "keep").write_text("VICTIM", encoding="utf-8")
        dest_parent.rename(tmp_path / "bak-parent.real")
        (tmp_path / "bak-parent").symlink_to(outside)

    monkeypatch.setattr(bak, "_mkdir_layers_at", swap_after)
    with pytest.raises((BackupError, VaultError), match="symlink"):
        pack(vault, dest)
    keeps = list(outside.rglob("keep"))
    assert len(keeps) == 1
    assert keeps[0].read_text(encoding="utf-8") == "VICTIM"
    leftovers = list((tmp_path / "bak-parent.real").glob(".out.*"))
    assert leftovers == []


def test_init_refuses_dangling_root(tmp_path: Path) -> None:
    root = tmp_path / "dangle-root"
    root.symlink_to(tmp_path / "created-by-init")
    with pytest.raises(VaultError, match="dangling symlink"):
        init_vault(root)
    assert not (tmp_path / "created-by-init").exists()


def test_pack_refuses_dest_symlink(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "bak"
    dest.symlink_to(outside)
    with pytest.raises(BackupError, match="symlink"):
        pack(vault, dest)
    assert list(outside.iterdir()) == []


def test_remove_staging_unlinks_symlink_not_target(tmp_path: Path) -> None:
    from capitalizator.ops.backup import _remove_staging

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("secret", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.symlink_to(outside)
    _remove_staging(staging)
    assert outside.is_dir()
    assert (outside / "keep").read_text(encoding="utf-8") == "secret"
    assert staging.exists() is False
    assert staging.is_symlink() is False


def test_knowledge_refuses_existing_file_via_parent_dir_symlink(tmp_path: Path) -> None:
    """Fact: os.open(path, O_NOFOLLOW) follows a parent dir symlink.

    dest/knowledge → outside; outside/desk.sqlite exists. Knowledge() used to write
    a SQLite header into the target (is_file True, last component is a regular file).
    """
    from capitalizator.ops.knowledge import Knowledge

    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "desk.sqlite"
    victim.write_bytes(b"")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "knowledge").symlink_to(outside)
    with pytest.raises((VaultError, ValueError), match="symlink"):
        Knowledge(dest / "knowledge" / "desk.sqlite")
    assert victim.read_bytes() == b""


def test_knowledge_refuses_symlink_db(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import Knowledge

    real = tmp_path / "real.sqlite"
    Knowledge(real).close()
    link = tmp_path / "desk.sqlite"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        Knowledge(link)


def test_knowledge_connect_does_not_write_through_swapped_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fact: sqlite3.connect(path) follows a symlink planted after the probe fd closes.

    We bind via /proc/self/fd/N instead. A swap of the name must not touch the target.
    """
    import capitalizator.ops.knowledge as knmod
    from capitalizator.ops.knowledge import Knowledge

    victim = tmp_path / "secret"
    victim.write_bytes(b"KEYMATERIAL")
    path = tmp_path / "desk.sqlite"
    real = knmod.connect_held_inode

    def swap_then_connect(fd: int, *, readonly: bool = False):
        if path.exists() and not path.is_symlink():
            path.unlink()
            path.symlink_to(victim)
        return real(fd, readonly=readonly)

    monkeypatch.setattr(knmod, "connect_held_inode", swap_then_connect)
    with pytest.raises(ValueError, match="symlink"):
        Knowledge(path)
    assert victim.read_bytes() == b"KEYMATERIAL"


def test_connect_held_inode_writes_held_file_not_symlink_target(tmp_path: Path) -> None:
    import os

    from capitalizator.ops.knowledge import connect_held_inode

    victim = tmp_path / "secret"
    victim.write_bytes(b"KEYMATERIAL")
    path = tmp_path / "desk.sqlite"
    nofollow = os.O_NOFOLLOW
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow, 0o644)
    try:
        path.unlink()
        path.symlink_to(victim)
        cx = connect_held_inode(fd)
        try:
            cx.executescript("CREATE TABLE t(x INT); INSERT INTO t VALUES (1);")
        finally:
            cx.close()
    finally:
        os.close(fd)
    assert victim.read_bytes() == b"KEYMATERIAL"
    assert path.is_symlink()


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


def test_init_refuses_dangling_layer_symlink(tmp_path: Path) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    (root / "knowledge").symlink_to(tmp_path / "missing-knowledge")
    (root / "tape").mkdir()
    (root / "reports").mkdir()
    with pytest.raises(VaultError, match="real directory|symlink"):
        init_vault(root)
    assert (root / "knowledge").is_symlink()
    assert not (tmp_path / "missing-knowledge").exists()


def test_init_refuses_dangling_secrets(tmp_path: Path) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "tape").mkdir()
    (root / "reports").mkdir()
    (root / "secrets").symlink_to(tmp_path / "missing-secrets")
    with pytest.raises(VaultError, match="secrets"):
        init_vault(root)
    assert (root / "secrets").is_symlink()
    assert not (tmp_path / "missing-secrets").exists()


def test_init_refuses_layer_dir_symlink(tmp_path: Path) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "knowledge").symlink_to(outside)
    with pytest.raises(VaultError, match="symlink|real directory"):
        init_vault(root)


def test_init_refuses_layout_symlink(tmp_path: Path) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.write_bytes(b"KEYMATERIAL")
    (root / "LAYOUT").symlink_to(secret)
    with pytest.raises(VaultError, match="symlink"):
        init_vault(root)
    assert secret.read_bytes() == b"KEYMATERIAL"


def test_write_regular_holds_dir_fd_across_parent_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fact: mkstemp(dir=parent) after ancestor swap writes into the symlink target.

    Hold the parent inode (openat) before the swap; bytes stay in the real dir.
    """
    import capitalizator.ops.vault as vault_mod
    from capitalizator.ops.vault import write_regular_bytes

    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    reports = dest_root / "reports"
    reports.mkdir()
    nested = reports / "nested"
    nested.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "nested").mkdir()
    real_open = vault_mod.open_real_dir_fd

    def open_then_swap(directory: Path, *, create: bool = True) -> int:
        fd = real_open(directory, create=create)
        reports.rename(tmp_path / "reports_real")
        (dest_root / "reports").symlink_to(outside)
        return fd

    monkeypatch.setattr(vault_mod, "open_real_dir_fd", open_then_swap)
    write_regular_bytes(nested / "keep.txt", b"DATA")
    assert (tmp_path / "reports_real" / "nested" / "keep.txt").read_bytes() == b"DATA"
    assert list((outside / "nested").iterdir()) == []


def test_copy_regular_refuses_parent_dir_symlink(tmp_path: Path) -> None:
    """Fact: Path.mkdir(parents=True) creates nested names *inside* a dir symlink.

    dest/reports → outside; dest/reports/nested.mkdir(parents=True) made
    outside/nested. nested itself is a real directory, so a parent.is_symlink()
    check after mkdir misses the leak. We walk every ancestor.
    """
    from capitalizator.ops.vault import copy_regular

    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / "reports").symlink_to(outside)
    with pytest.raises(VaultError, match="symlink"):
        copy_regular(src, dest_root / "reports" / "nested" / "keep.txt")
    assert list(outside.iterdir()) == []


def test_copy_regular_refuses_existing_nested_via_symlink(tmp_path: Path) -> None:
    from capitalizator.ops.vault import copy_regular

    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "nested").mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / "reports").symlink_to(outside)
    with pytest.raises(VaultError, match="symlink"):
        copy_regular(src, dest_root / "reports" / "nested" / "keep.txt")
    assert list((outside / "nested").iterdir()) == []


def test_write_regular_refuses_parent_dir_symlink(tmp_path: Path) -> None:
    from capitalizator.ops.vault import write_regular_text

    outside = tmp_path / "outside"
    outside.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / "reports").symlink_to(outside)
    with pytest.raises(VaultError, match="symlink"):
        write_regular_text(dest_root / "reports" / "nested" / "LAYOUT", "1\n")
    assert list(outside.iterdir()) == []


def test_snapshot_refuses_parent_dir_symlink(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import Knowledge

    src = tmp_path / "src.sqlite"
    kn = Knowledge(src)
    kn.append_link("zone|DEFEND")
    outside = tmp_path / "outside"
    outside.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / "knowledge").symlink_to(outside)
    try:
        with pytest.raises((VaultError, ValueError), match="symlink"):
            kn.snapshot_to(dest_root / "knowledge" / "nested" / "desk.sqlite")
    finally:
        kn.close()
    assert list(outside.rglob("*")) == []


def test_knowledge_create_refuses_parent_dir_symlink(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import Knowledge

    outside = tmp_path / "outside"
    outside.mkdir()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    (dest_root / "knowledge").symlink_to(outside)
    with pytest.raises((VaultError, ValueError), match="symlink"):
        Knowledge(dest_root / "knowledge" / "nested" / "desk.sqlite")
    assert list(outside.iterdir()) == []


def test_copy_plain_refuses_dest_dir_symlink(tmp_path: Path) -> None:
    from capitalizator.ops.backup import REPORT_SUFFIX, BackupError, _copy_plain

    vault = init_vault(tmp_path / "desk")
    (vault.reports / "keep.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "dest_reports"
    dest.symlink_to(outside)
    with pytest.raises(BackupError, match="symlink"):
        _copy_plain(vault.reports, dest, suffixes=REPORT_SUFFIX)
    assert list(outside.iterdir()) == []


def test_lock_file_is_not_packed(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    ParquetSink(vault.tape).write(_event())
    assert list(vault.tape.rglob("*.lock"))
    manifest = pack(vault, tmp_path / "bak")
    assert manifest["counts"]["parquet_rows"] == 1
    listed = " ".join(manifest["files"])
    assert ".lock" not in listed

"""Sandbox rows join live journal when the touch_id is new or a hole."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.hyexec.import_labels import import_rows, main
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault

_HX0 = FEATURE_KEYS[0]


def _row(tid: str, r_net: str = "1") -> dict:
    body = {key: "1" for key in FEATURE_KEYS}
    body["touch_id"] = tid
    body["paper"] = {"shadow": {"filled": True, "r_net": r_net}}
    return body


def test_import_skips_existing_touch_id() -> None:
    dest = [_row("live")]
    merged, n, filled = import_rows(source=[_row("live", "9"), _row("sand")], dest=dest)
    assert n == 1
    assert filled == 0
    assert [r["touch_id"] for r in merged] == ["live", "sand"]
    assert merged[0]["paper"]["shadow"]["r_net"] == "1"


def test_import_fills_empty_shadow_r_net() -> None:
    dest = [_row("live")]
    dest[0]["paper"] = {
        "shadow": {"filled": False, "r_net": ""},
        "fade": {"note": "keep"},
    }
    src = _row("live", "2")
    src["paper"]["fade"] = {"note": "sandbox"}
    merged, n, filled = import_rows(source=[src], dest=dest)
    assert n == 0
    assert filled == 1
    assert merged[0]["paper"]["shadow"]["r_net"] == "2"
    assert merged[0]["paper"]["fade"]["note"] == "keep"


def test_import_fills_hx_holes_on_same_id() -> None:
    dest = [_row("live")]
    dest[0][_HX0] = None
    src = _row("live", "9")
    src[_HX0] = "0.4"
    merged, n, filled = import_rows(source=[src], dest=dest)
    assert n == 0
    assert filled == 1
    assert merged[0][_HX0] == "0.4"
    assert merged[0]["paper"]["shadow"]["r_net"] == "1"


def test_import_does_not_close_open_live_shadow() -> None:
    dest = [_row("live")]
    dest[0]["paper"] = {"fade": {"note": "keep"}}
    dest[0]["paper_ids"] = {"shadow": "p-live"}
    src = _row("live", "2")
    merged, n, filled = import_rows(source=[src], dest=dest)
    assert n == 0
    assert filled == 0
    assert merged[0].get("paper", {}).get("shadow") is None
    assert merged[0]["paper"]["fade"]["note"] == "keep"


def test_import_fills_hx_on_open_live_shadow() -> None:
    dest = [_row("live")]
    dest[0][_HX0] = None
    dest[0]["paper"] = {}
    dest[0]["paper_ids"] = {"shadow": "p-live"}
    src = _row("live", "2")
    src[_HX0] = "0.4"
    merged, n, filled = import_rows(source=[src], dest=dest)
    assert n == 0
    assert filled == 1
    assert merged[0][_HX0] == "0.4"
    assert merged[0].get("paper", {}).get("shadow") is None


def test_cli_refuses_without_ack(tmp_path: Path) -> None:
    src = init_vault(tmp_path / "sand")
    dst = init_vault(tmp_path / "live")
    with pytest.raises(SystemExit, match="--ack"):
        main(["--from-userdir", str(src.root), "--to-userdir", str(dst.root)])


def test_cli_ack_copies_missing_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = init_vault(tmp_path / "sand")
    dst = init_vault(tmp_path / "live")
    s = open_knowledge(src)
    d = open_knowledge(dst)
    try:
        s.put_journal_touch("sand", _row("sand"))
        s.put_journal_touch("live", _row("live", "9"))
        d.put_journal_touch("live", _row("live", "1"))
    finally:
        s.close()
        d.close()
    assert main(
        ["--from-userdir", str(src.root), "--to-userdir", str(dst.root), "--ack"]
    ) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["imported"] == 1
    live = open_knowledge(dst)
    try:
        ids = {r["touch_id"] for r in live.journal_rows()}
        by_id = {r["touch_id"]: r for r in live.journal_rows()}
    finally:
        live.close()
    assert ids == {"live", "sand"}
    assert by_id["live"]["paper"]["shadow"]["r_net"] == "1"


def test_cli_ack_fills_empty_live_r_net(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = init_vault(tmp_path / "sand")
    dst = init_vault(tmp_path / "live")
    hole = _row("live")
    hole["paper"] = {"shadow": {"filled": False, "r_net": ""}}
    s = open_knowledge(src)
    d = open_knowledge(dst)
    try:
        s.put_journal_touch("live", _row("live", "2"))
        d.put_journal_touch("live", hole)
    finally:
        s.close()
        d.close()
    assert main(
        ["--from-userdir", str(src.root), "--to-userdir", str(dst.root), "--ack"]
    ) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["imported"] == 0
    assert out["filled"] == 1
    live = open_knowledge(dst)
    try:
        row = next(r for r in live.journal_rows() if r["touch_id"] == "live")
    finally:
        live.close()
    assert row["paper"]["shadow"]["r_net"] == "2"

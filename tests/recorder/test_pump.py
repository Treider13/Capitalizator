"""Injected frames write parquet and flip recording. Live WS stays off."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from capitalizator.recorder.app import RecorderApp, main
from capitalizator.recorder.pump import pump_jsonl

TRADES = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_trades_100.jsonl"
BOOK = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_book_snapshot_20_diffs.jsonl"
RECV = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
# Fixture T/ts = 1725024600000 ms. Partition follows exchange_ts, not recv_ts.
_FIX_TS = datetime.fromtimestamp(1_725_024_600, tz=UTC)
_DAY = _FIX_TS.strftime("%Y-%m-%d")
_HOUR = _FIX_TS.strftime("%H")


def test_minutes_has_no_socket_and_refuses() -> None:
    """`--minutes` used to print `"live": true` after writing nothing (audit §4)."""
    with pytest.raises(SystemExit, match="live-ws"):
        main(["--minutes", "60"])
    with pytest.raises(SystemExit, match="live-ws"):
        main(["--minutes", "1", "--data-root", "/tmp/x", "--symbol", "BTCUSDT"])


def test_from_jsonl_trades_writes_exact_count(tmp_path: Path) -> None:
    app = RecorderApp()
    n = pump_jsonl(app, tmp_path, TRADES, stream="trades", recv_ts=RECV)
    assert n == 100
    assert app.recording is True
    assert app.readyz() == 200
    assert app.accepted_count == 100
    path = tmp_path / "bybit" / "BTCUSDT" / "trades" / f"date={_DAY}" / f"hour={_HOUR}.parquet"
    assert path.exists()
    assert pq.ParquetFile(path).read().num_rows == 100


def test_cli_from_jsonl_prints_accepted(tmp_path: Path) -> None:
    code = main(
        [
            "--from-jsonl",
            str(TRADES),
            "--data-root",
            str(tmp_path),
            "--stream",
            "trades",
        ]
    )
    assert code == 0
    path = tmp_path / "bybit" / "BTCUSDT" / "trades" / f"date={_DAY}" / f"hour={_HOUR}.parquet"
    assert pq.ParquetFile(path).read().num_rows == 100


def test_cli_from_jsonl_requires_data_root() -> None:
    with pytest.raises(SystemExit, match="data-root"):
        main(["--from-jsonl", str(TRADES)])


def test_book_pump_writes_snapshot_diffs_and_bbo(tmp_path: Path) -> None:
    app = RecorderApp()
    n = pump_jsonl(app, tmp_path, BOOK, stream="book", recv_ts=RECV)
    # 1 snapshot + 20 diffs + 21 bbo
    assert n == 42
    assert app.recording is True
    snaps = pq.ParquetFile(
        tmp_path / "bybit" / "BTCUSDT" / "snapshot" / f"date={_DAY}" / f"hour={_HOUR}.parquet"
    ).read()
    diffs = pq.ParquetFile(
        tmp_path / "bybit" / "BTCUSDT" / "book_diff" / f"date={_DAY}" / f"hour={_HOUR}.parquet"
    ).read()
    bbos = pq.ParquetFile(
        tmp_path / "bybit" / "BTCUSDT" / "bbo" / f"date={_DAY}" / f"hour={_HOUR}.parquet"
    ).read()
    assert snaps.num_rows == 1
    assert diffs.num_rows == 20
    assert bbos.num_rows == 21


def test_unknown_stream_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown pump stream"):
        pump_jsonl(RecorderApp(), tmp_path, TRADES, stream="funding")


def test_pump_does_not_import_signer(tmp_path: Path) -> None:
    import sys

    sys.modules.pop("capitalizator.signer", None)
    pump_jsonl(RecorderApp(), tmp_path, TRADES, stream="trades", recv_ts=RECV)
    assert "capitalizator.signer" not in sys.modules


def test_empty_jsonl_does_not_claim_recording(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    app = RecorderApp()
    assert pump_jsonl(app, tmp_path / "out", empty, stream="trades") == 0
    assert app.recording is False
    assert app.readyz() == 503


def test_subscribe_ack_is_not_written(tmp_path: Path) -> None:
    mixed = tmp_path / "mixed.jsonl"
    mixed.write_text(
        '{"op":"subscribe","success":true}\n'
        '{"T":1725024600000,"s":"BTCUSDT","S":"Buy","v":"0.001","p":"1","i":"a"}\n',
        encoding="utf-8",
    )
    app = RecorderApp()
    n = pump_jsonl(app, tmp_path / "out", mixed, stream="trades", recv_ts=RECV)
    assert n == 1
    assert app.accepted_count == 1


def test_non_object_jsonl_line_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("[1,2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        pump_jsonl(RecorderApp(), tmp_path / "out", bad, stream="trades")


def test_cli_output_is_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--from-jsonl", str(TRADES), "--data-root", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["accepted"] == 100
    assert payload["recording"] is True
    assert payload["readyz"] == 200
    assert payload["lag"]["n"] == 100
    assert "p50_ms" in payload["lag"]
    assert "p95_ms" in payload["lag"]

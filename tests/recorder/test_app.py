"""0.1.3: healthz 200, readyz 503 until recording, no signer import."""

from __future__ import annotations

import capitalizator.recorder as recorder_pkg
from capitalizator.recorder.app import RecorderApp


def test_healthz_readyz() -> None:
    app = RecorderApp()
    assert app.healthz() == 200
    assert app.readyz() == 503
    app.recording = True
    assert app.readyz() == 200


def test_metrics_text() -> None:
    app = RecorderApp()
    app.accepted_count = 3
    text = app.metrics()
    assert "capitalizator_recorder_accepted_total 3" in text


def test_recorder_does_not_import_signer() -> None:
    assert "capitalizator.signer" not in recorder_pkg.__dict__
    assert "signer" not in recorder_pkg.__dict__


def test_live_hour_flag_is_disabled() -> None:
    from capitalizator.recorder.app import main

    try:
        main(["--minutes", "60"])
    except SystemExit as exc:
        assert "live WS hour is not enabled" in str(exc)
        return
    raise AssertionError("live hour must refuse")

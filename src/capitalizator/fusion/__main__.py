"""Start the two-mode threaded runtime; no 24-hour BTC tape prerequisite."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path

from capitalizator.fusion.config import Config
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.web import server


def main() -> int:
    parser = argparse.ArgumentParser(description="Capitalizator Atlas / Bybit Demo and Live")
    parser.add_argument("--userdir", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    local_config = args.userdir / "config.json"
    config_path = args.config or local_config
    # An explicit path is an operator instruction, never an optional fallback.
    config = Config.load(args.config or (local_config if local_config.exists() else None))
    if args.status:
        from urllib.request import urlopen

        with urlopen(f"http://127.0.0.1:{config.api_port}/api/status", timeout=5) as response:
            print(response.read().decode())
        return 0
    stop = threading.Event()
    received_signal: list[int] = []

    def stop_signal(signum: int, _frame: object) -> None:
        received_signal.append(signum)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop_signal)
    while not stop.is_set():
        runtime = Runtime(args.userdir, config, config_path=config_path)
        http = None
        web_thread = None
        fatal = False
        try:
            http = server(runtime, config.api_port)
            web_thread = threading.Thread(target=http.serve_forever, name="console", daemon=False)
            runtime.start()
            web_thread.start()
            print(
                json.dumps(
                    {
                        "mode": runtime.shared.mode,
                        "console": f"http://127.0.0.1:{config.api_port}",
                        "btc_24h_required": False,
                    }
                ),
                flush=True,
            )
            while not stop.wait(0.1):
                if runtime.supervisor.failed.is_set():
                    runtime.shared.halt("worker_failure")
                    break
                if runtime.restart_requested.is_set():
                    break
        except BaseException as exc:
            fatal = True
            runtime.diagnostics.failure("main", exc)
            raise
        finally:
            runtime.supervisor.stop.set()
            runtime.shared.broker_wake.set()
            if http is not None and web_thread is not None and web_thread.is_alive():
                http.shutdown()
                web_thread.join(5)
            if http is not None:
                http.server_close()
            try:
                runtime.close()
            except BaseException as exc:
                runtime.diagnostics.failure("shutdown", exc)
                raise
            runtime.diagnostics.record(
                "shutdown",
                reason=(
                    "main_failure"
                    if fatal
                    else "worker_failure"
                    if runtime.supervisor.failed.is_set()
                    else "signal"
                    if received_signal
                    else "configuration_restart"
                ),
                signals=received_signal,
                exit_code=1 if fatal or runtime.supervisor.failed.is_set() else 0,
            )
        if runtime.supervisor.failed.is_set():
            return 1
        if not runtime.restart_requested.is_set() or runtime.supervisor.failed.is_set():
            break
        config = Config.load(config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

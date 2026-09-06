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


def main() -> None:
    parser = argparse.ArgumentParser(description="Capitalizator Atlas / Bybit Demo and Live")
    parser.add_argument("--userdir", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    local_config = args.userdir / "config.json"
    config_path = args.config or local_config
    config = Config.load(config_path if config_path.is_file() else None)
    if args.status:
        from urllib.request import urlopen

        with urlopen(f"http://127.0.0.1:{config.api_port}/api/status", timeout=5) as response:
            print(response.read().decode())
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        runtime = Runtime(args.userdir, config, config_path=config_path)
        http = server(runtime, config.api_port)
        web_thread = threading.Thread(target=http.serve_forever, name="console", daemon=False)
        try:
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
        finally:
            runtime.supervisor.stop.set()
            runtime.shared.broker_wake.set()
            if web_thread.is_alive():
                http.shutdown()
                web_thread.join(5)
            http.server_close()
            runtime.close()
        if not runtime.restart_requested.is_set() or runtime.supervisor.failed.is_set():
            break
        config = Config.load(config_path)


if __name__ == "__main__":
    main()

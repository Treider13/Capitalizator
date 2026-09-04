"""Recorder process: health + injected-frame pump. No signer import. No keys."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


class RecorderApp:
    """In-process status. Recording flag is explicit; default is not ready."""

    def __init__(self) -> None:
        self.recording = False
        self.accepted_count = 0
        self.last_lag: dict[str, float] | None = None

    def healthz(self) -> int:
        return 200

    def readyz(self) -> int:
        return 200 if self.recording else 503

    def metrics(self) -> str:
        return (
            "# HELP capitalizator_recorder_accepted_total Events written\n"
            "# TYPE capitalizator_recorder_accepted_total counter\n"
            f"capitalizator_recorder_accepted_total {self.accepted_count}\n"
        )


def _handler(app: RecorderApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                body, code = b"ok", app.healthz()
            elif self.path == "/readyz":
                body, code = (b"ready" if app.recording else b"not-recording"), app.readyz()
            elif self.path == "/metrics":
                body, code = app.metrics().encode(), 200
            else:
                body, code = b"not-found", 404
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capitalizator recorder (no keys)")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--stream", default="trades")
    parser.add_argument("--minutes", type=int, default=0)
    parser.add_argument("--from-jsonl", default=None)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--live-ws",
        action="store_true",
        help="24/7 public WebSocket recorder (pybit) for the desk universe; --userdir for status",
    )
    parser.add_argument("--userdir", default=None)
    parser.add_argument("--testnet", action="store_true")
    parser.add_argument(
        "--universe",
        choices=("week0", "desk"),
        default=os.environ.get("CAP_UNIVERSE", "week0"),
        help="week0 = BTC+ETH (PHASE-BUILD canon until 24h of tape); desk = the top-10 list",
    )
    args = parser.parse_args(argv)
    app = RecorderApp()
    if args.live_ws:
        if not args.data_root and not args.userdir:
            raise SystemExit("--live-ws needs --data-root or --userdir")
        import signal

        from capitalizator.ops.knowledge import open_knowledge
        from capitalizator.ops.vault import load_vault
        from capitalizator.recorder.live_ws import LiveRecorder, make_public_ws
        from capitalizator.screener.universe import (
            default_week0_path,
            load_desk_universe,
            load_universe,
        )

        knowledge = None
        data_root = Path(args.data_root) if args.data_root else None
        if args.userdir:
            vault = load_vault(Path(args.userdir))
            knowledge = open_knowledge(vault)
            data_root = data_root or vault.tape
        assert data_root is not None
        stopped = {"v": False}

        def _stop(signum: int, frame: object) -> None:
            stopped["v"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        if args.universe == "week0":
            universe = load_universe(default_week0_path())
        else:
            universe = load_desk_universe()  # honours CAP_UNIVERSE / the applied file too
        rec = LiveRecorder(
            symbols=list(universe.symbols),
            data_root=data_root,
            ws_factory=lambda: make_public_ws(testnet=args.testnet),
            knowledge=knowledge,
            rest_fallback=True,
        )
        app.recording = True
        hello = {
            "live_ws": True,
            "universe": args.universe,
            "n_symbols": len(rec.symbols),
            "data_root": str(data_root),
        }
        print(json.dumps(hello), flush=True)
        try:
            def _universe() -> list[str]:
                if args.universe == "week0":
                    return list(load_universe(default_week0_path()).symbols)
                return list(load_desk_universe().symbols)

            rec.run(
                should_stop=lambda: stopped["v"],
                testnet=args.testnet,
                universe_fn=_universe,
            )
        finally:
            if knowledge is not None:
                knowledge.close()
        print(json.dumps(rec.status(), default=str))
        return 0
    if args.from_jsonl:
        if not args.data_root:
            raise SystemExit("--data-root is required with --from-jsonl")
        from capitalizator.recorder.pump import pump_jsonl

        accepted = pump_jsonl(
            app, Path(args.data_root), Path(args.from_jsonl), stream=args.stream
        )
        payload = {
            "accepted": accepted,
            "recording": app.recording,
            "readyz": app.readyz(),
            "symbol": args.symbol,
        }
        if app.last_lag is not None:
            payload["lag"] = app.last_lag
        print(json.dumps(payload))
        if args.serve:
            server = HTTPServer((args.host, args.port), _handler(app))
            server.serve_forever()
        return 0
    if args.minutes and args.minutes > 0:
        # `--minutes` had no socket behind it: it printed `"live": true` after writing
        # zero events (audit §4). A timed live run is `--live-ws` with a deadline.
        raise SystemExit(
            "--minutes has no socket: use --live-ws --data-root DIR (add --testnet for the "
            "testnet host) and stop it with SIGINT/SIGTERM or a supervisor timeout"
        )
    if args.serve:
        server = HTTPServer((args.host, args.port), _handler(app))
        server.serve_forever()
        return 0
    print(json.dumps({"healthz": app.healthz(), "readyz": app.readyz(), "symbol": args.symbol}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

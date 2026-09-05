"""Live hyexec process: timing facts only. Does not import xgboost. Does not send."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hyexec timing loop. No orders.")
    parser.add_argument("--userdir", required=True)
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

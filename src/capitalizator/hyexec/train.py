"""Train extra. Contour A never imports this file. xgboost stays behind the extra."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hyexec train. Requires the hyexec extra.")
    parser.add_argument("--userdir", required=True)
    parser.parse_args(argv)
    try:
        import xgboost  # noqa: F401
        from capitalizator.hyexec.river_adwin import drift_on  # noqa: F401
    except ImportError:
        raise SystemExit("hyexec extra missing: pip install -e '.[hyexec]'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

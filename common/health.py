"""Health checks for background workers, which have no HTTP endpoint.

A worker calls beat() whenever it has shown it works (connected to the broker
and processing), one heartbeat file per task. Docker's healthcheck runs

    python -m common.health HEARTBEAT_FILE... [--max-age SECONDS]

which fails if any heartbeat file is missing or older than --max-age.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

MAX_AGE = 30.0


def beat(path: str) -> None:
    with open(path, "a"):
        pass
    os.utime(path)


def is_fresh(path: str, max_age: float = MAX_AGE) -> bool:
    try:
        return time.time() - os.path.getmtime(path) <= max_age
    except OSError:
        return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m common.health",
                                description="Fail unless every heartbeat file is recent.")
    p.add_argument("files", nargs="+", metavar="HEARTBEAT_FILE")
    p.add_argument("--max-age", type=float, default=MAX_AGE, metavar="SECONDS")
    args = p.parse_args(argv)
    stale = [f for f in args.files if not is_fresh(f, args.max_age)]
    for f in stale:
        print(f"unhealthy: no heartbeat in {f} within {args.max_age:g}s", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

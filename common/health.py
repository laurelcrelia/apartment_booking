"""Health checks for background workers, which have no HTTP endpoint.

A worker calls beat() whenever it has shown it works (connected to the broker
and processing). Docker's healthcheck runs

    python -m common.health HEARTBEAT_FILE [MAX_AGE_SECONDS]

which fails if the heartbeat file is missing or older than MAX_AGE_SECONDS.
"""
from __future__ import annotations

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
    args = sys.argv[1:] if argv is None else argv
    if not 1 <= len(args) <= 2:
        print("usage: python -m common.health HEARTBEAT_FILE [MAX_AGE_SECONDS]", file=sys.stderr)
        return 2
    max_age = float(args[1]) if len(args) == 2 else MAX_AGE
    if is_fresh(args[0], max_age):
        return 0
    print(f"unhealthy: no heartbeat in {args[0]} within {max_age:g}s", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

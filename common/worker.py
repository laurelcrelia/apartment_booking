"""Background worker: runs a service's relay and consumer side by side.

Each task runs in its own thread with its own broker connection (pika
connections aren't thread-safe). Tasks are meant to run forever; if one stops
anyway, the worker exits, so Docker's restart policy starts it again instead
of leaving a half-working process behind.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def run_tasks(tasks: dict, check_every: float = 1.0) -> str:
    """Start each task in a thread; return the name of the first one that stops."""
    stopped = threading.Event()
    finished = []

    def run(name, task):
        try:
            task()
        except BaseException:
            log.exception("%s crashed", name)
        finally:
            finished.append(name)
            stopped.set()

    for name, task in tasks.items():
        threading.Thread(target=run, args=(name, task), name=name, daemon=True).start()
    while not stopped.wait(check_every):
        pass
    log.error("%s stopped; exiting so the worker gets restarted", finished[0])
    return finished[0]

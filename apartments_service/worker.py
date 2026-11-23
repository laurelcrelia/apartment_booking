"""Apartments worker: publishes apartment events and consumes booking events.

    RABBITMQ_URL=amqp://... APARTMENTS_DB=apartments.db python -m apartments_service.worker

Runs next to the apartments service, on the same database: its relay
publishes the outbox to the "apartments" exchange, and its consumer keeps the
bookings replica up to date from the "bookings" exchange.
"""
from __future__ import annotations

import logging
import os
import sys
from functools import partial

from common.events import APARTMENTS_EXCHANGE, BOOKINGS_EXCHANGE

from .consumer import BINDING, QUEUE, on_message
from .repo import ApartmentRepo

RELAY_HEARTBEAT = "/tmp/apartments-relay.heartbeat"
CONSUMER_HEARTBEAT = "/tmp/apartments-consumer.heartbeat"


def main() -> int:  # pragma: no cover - needs a broker; exercised by the Compose CI job
    from common.health import beat
    from common.rabbitmq import consume, run_forever
    from common.relay import run_relay
    from common.worker import run_tasks

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    repo = ApartmentRepo(os.environ.get("APARTMENTS_DB", "apartments.db"))
    url = os.environ["RABBITMQ_URL"]
    run_tasks({
        "relay": partial(run_relay, repo.outbox, url, APARTMENTS_EXCHANGE, RELAY_HEARTBEAT),
        "consumer": partial(run_forever, lambda: consume(
            url, BOOKINGS_EXCHANGE, QUEUE, BINDING, partial(on_message, repo),
            on_tick=partial(beat, CONSUMER_HEARTBEAT)), "consumer"),
    })
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

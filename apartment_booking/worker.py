"""Booking worker: publishes booking events and consumes apartment events.

    RABBITMQ_URL=amqp://... BOOKINGS_DB=bookings.db python -m apartment_booking.worker

Runs next to the web app, on the bookings database: its relay publishes the
outbox to the "bookings" exchange, and its consumer keeps the apartments
replica up to date from the "apartments" exchange.
"""
from __future__ import annotations

import logging
import os
import sys
from functools import partial

from common.events import APARTMENTS_EXCHANGE, BOOKINGS_EXCHANGE

from .consumer import BINDING, QUEUE, on_message
from .repos import BookingRepo

RELAY_HEARTBEAT = "/tmp/bookings-relay.heartbeat"
CONSUMER_HEARTBEAT = "/tmp/bookings-consumer.heartbeat"


def main() -> int:  # pragma: no cover - needs a broker; exercised by the Compose CI job
    from common.health import beat
    from common.rabbitmq import consume, run_forever
    from common.relay import run_relay
    from common.worker import run_tasks

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    repo = BookingRepo(os.environ.get("BOOKINGS_DB", "bookings.db"))
    url = os.environ["RABBITMQ_URL"]
    run_tasks({
        "relay": partial(run_relay, repo.outbox, url, BOOKINGS_EXCHANGE, RELAY_HEARTBEAT),
        "consumer": partial(run_forever, lambda: consume(
            url, APARTMENTS_EXCHANGE, QUEUE, BINDING, partial(on_message, repo),
            on_tick=partial(beat, CONSUMER_HEARTBEAT)), "consumer"),
    })
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

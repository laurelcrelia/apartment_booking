"""Booking consumer: keeps the apartments replica in bookings.db up to date.

    RABBITMQ_URL=amqp://... BOOKINGS_DB=bookings.db python -m apartment_booking.consumer

Consumes the apartments service's events from the durable queue QUEUE. Each
event is applied in one transaction together with recording its event_id, so
a redelivered event changes nothing, and a change is applied only if its
version is newer than what the replica has, so events arriving out of order
can't roll an apartment back.
"""
from __future__ import annotations

import logging
import os
from functools import partial

from common.events import APARTMENT_CREATED, APARTMENT_DELETED, APARTMENT_UPDATED, decode

from .repos import BookingRepo

QUEUE = "bookings.apartments"
BINDING = "apartment.*"
HEARTBEAT_FILE = "/tmp/booking-consumer.heartbeat"

log = logging.getLogger("apartment_booking.consumer")


def handle_event(repo: BookingRepo, event: dict) -> bool:
    """Apply one event to the replica; returns False if it changed nothing."""
    data, event_type = event["data"], event["type"]
    with repo.writing() as table:
        if table.event_processed(event["event_id"]):
            return False
        current = table.replica_get(data["id"])
        newer = current is None or data["version"] > current["version"]
        applied = False
        if newer and event_type in (APARTMENT_CREATED, APARTMENT_UPDATED):
            table.replica_put(data, data["version"])
            applied = True
        elif newer and event_type == APARTMENT_DELETED:
            table.replica_delete(data["id"], data["version"])
            applied = True
        table.record_event(event["event_id"])
        return applied


def on_message(repo: BookingRepo, body: bytes) -> None:
    try:
        event = decode(body)
    except ValueError as e:
        # Redelivering would fail the same way forever: log it and drop it.
        log.warning("dropping malformed event: %s", e)
        return
    if handle_event(repo, event):
        log.info("applied %s for apartment %s (version %s)",
                 event["type"], event["data"]["id"], event["data"]["version"])


def main() -> None:  # pragma: no cover - needs a broker; exercised by the Compose CI job
    from common.health import beat
    from common.rabbitmq import consume, run_forever

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    repo = BookingRepo(os.environ.get("BOOKINGS_DB", "bookings.db"))
    url = os.environ["RABBITMQ_URL"]
    heartbeat = os.environ.get("HEARTBEAT_FILE", HEARTBEAT_FILE)
    run_forever(lambda: consume(url, QUEUE, BINDING, partial(on_message, repo),
                                on_tick=partial(beat, heartbeat)), "consumer")


if __name__ == "__main__":  # pragma: no cover
    main()

"""Outbox relay: publishes the apartments service's outbox events.

    RABBITMQ_URL=amqp://... APARTMENTS_DB=apartments.db python -m apartments_service.relay

Runs as its own process next to the apartments service (one relay per
database). It polls the outbox, publishes each event with publisher confirms
and only then marks it published, so an event is never lost; after a crash it
may be published twice, which consumers tolerate.
"""
from __future__ import annotations

import logging
import os

from .repo import ApartmentRepo, Outbox

POLL_SECONDS = 0.5

log = logging.getLogger("apartments_service.relay")


class Relay:
    """Moves events from the outbox to a publisher: anything with publish(event)."""

    def __init__(self, outbox: Outbox, publisher):
        self.outbox = outbox
        self.publisher = publisher

    def publish_pending(self) -> int:
        """Publish everything pending; returns how many events were published."""
        self.outbox.snapshot_once()
        count = 0
        while True:
            batch = self.outbox.pending()
            if not batch:
                return count
            for row_id, event in batch:
                self.publisher.publish(event)
                self.outbox.mark_published(row_id)
                count += 1


def main() -> None:  # pragma: no cover - needs a broker; exercised by the Compose CI job
    from common.rabbitmq import PikaPublisher, run_forever

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    outbox = ApartmentRepo(os.environ.get("APARTMENTS_DB", "apartments.db")).outbox
    url = os.environ["RABBITMQ_URL"]

    def work():
        from pika.exceptions import UnroutableError

        publisher = PikaPublisher(url)
        log.info("connected; publishing outbox events")
        try:
            relay = Relay(outbox, publisher)
            while True:
                try:
                    count = relay.publish_pending()
                except UnroutableError:
                    # No consumer has bound its queue yet (e.g. right after
                    # startup); the event stays pending, so just try again soon.
                    log.info("no queue bound to the exchange yet; waiting")
                    publisher.sleep(1)
                    continue
                if count:
                    log.info("published %d event(s)", count)
                publisher.sleep(POLL_SECONDS)
        finally:
            publisher.close()

    run_forever(work, "relay")


if __name__ == "__main__":  # pragma: no cover
    main()

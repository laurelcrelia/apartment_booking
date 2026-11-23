"""Outbox relay: publishes a service's outbox events.

One relay per database runs in that service's worker process. It polls the
outbox, publishes each event with publisher confirms and only then marks it
published, so an event is never lost; after a crash it may be published
twice, which consumers tolerate.
"""
from __future__ import annotations

import logging

from .outbox import Outbox

POLL_SECONDS = 0.5

log = logging.getLogger(__name__)


class Relay:
    """Moves events from an outbox to a publisher: anything with publish(event)."""

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


def run_relay(outbox: Outbox, url: str, exchange: str, heartbeat: str) -> None:  # pragma: no cover
    """Publish the outbox to RabbitMQ forever. Needs a broker; exercised by the Compose CI job."""
    from pika.exceptions import UnroutableError

    from .health import beat
    from .rabbitmq import PikaPublisher, run_forever

    def work():
        publisher = PikaPublisher(url, exchange)
        log.info("connected; publishing outbox events to exchange %s", exchange)
        try:
            relay = Relay(outbox, publisher)
            while True:
                beat(heartbeat)  # connected and polling: healthy
                try:
                    count = relay.publish_pending()
                except UnroutableError:
                    # No consumer has bound its queue yet (e.g. right after
                    # startup); the event stays pending, so just try again soon.
                    log.info("no queue bound to exchange %s yet; waiting", exchange)
                    publisher.sleep(1)
                    continue
                if count:
                    log.info("published %d event(s) to %s", count, exchange)
                publisher.sleep(POLL_SECONDS)
        finally:
            publisher.close()

    run_forever(work, f"relay to {exchange}")

"""Running the apartments service inside the booking app's process.

Used when APARTMENTS_URL is not set: tests, the Playwright suite and a plain
`flask run`. Events still go through each service's outbox and the same
handlers the workers use, but are delivered right away in both directions
instead of through RabbitMQ, so both replicas are always up to date.
"""
from __future__ import annotations

from common.events import decode, encode


class LocalPublisher:
    """A relay publisher that hands each event straight to handler(event)."""

    def __init__(self, handler):
        self.handler = handler

    def publish(self, event: dict) -> None:
        # Through JSON, like a real message, so nothing non-serializable slips through.
        self.handler(decode(encode(event)))


class LocalBookings:
    """The booking repository, as the apartments service's link for the delete check."""

    def __init__(self, bookings):
        self.bookings = bookings

    def active_bookings(self, apt_id: int) -> list[dict]:
        with self.bookings.reading() as table:
            return table.list(apt_id=apt_id)


class LocalApartments:
    """The in-process ApartmentService, delivering its events after every change."""

    def __init__(self, service, relay):
        self.service = service
        self.relay = relay
        relay.publish_pending()  # apartments that existed before events did

    def get(self, apt_id: int) -> dict:
        return self.service.get(apt_id)

    def list(self) -> list[dict]:
        return self.service.list()

    def add(self, *args, **kwargs) -> dict:
        return self._delivering(self.service.add, *args, **kwargs)

    def update(self, *args, **kwargs) -> dict:
        return self._delivering(self.service.update, *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._delivering(self.service.delete, *args, **kwargs)

    def _delivering(self, method, *args, **kwargs):
        result = method(*args, **kwargs)
        self.relay.publish_pending()
        return result

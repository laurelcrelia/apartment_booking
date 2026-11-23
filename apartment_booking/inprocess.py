"""Running the apartments service inside the booking app's process.

Used when APARTMENTS_URL is not set: tests, the Playwright suite and a plain
`flask run`. Events still go through the apartments outbox and the same
handler the booking consumer uses, but are delivered right away instead of
through RabbitMQ, so the replica is always up to date.
"""
from __future__ import annotations

from common.events import decode, encode

from .consumer import handle_event
from .repos import BookingRepo


class LocalPublisher:
    """A relay publisher that hands events straight to the booking side."""

    def __init__(self, bookings: BookingRepo):
        self.bookings = bookings

    def publish(self, event: dict) -> None:
        # Through JSON, like a real message, so nothing non-serializable slips through.
        handle_event(self.bookings, decode(encode(event)))


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

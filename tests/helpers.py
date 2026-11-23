"""Test helpers."""
from functools import partial

from apartments_service.consumer import handle_booking_event
from apartments_service.repo import ApartmentRepo
from apartments_service.service import ApartmentService
from bookings_service.consumer import handle_event
from bookings_service.repos import BookingRepo
from bookings_service.service import BookingService
from common.relay import Relay
from devstack import LocalPublisher


class BookingsLink:
    """The apartments service's link to bookings (HttpBookings in production), reading the repository."""

    def __init__(self, repo: BookingRepo):
        self.repo = repo

    def active_bookings(self, apt_id):
        with self.repo.reading() as table:
            return table.list(apt_id=apt_id)


class Services:
    """Both services' rules on in-memory (or given) databases, linked directly instead
    of over HTTP, with events delivered after every change.

    For testing the rules quickly; the HTTP wiring is tested through devstack.
    The methods are named like the operations of the public API.
    """

    def __init__(self, apartments_db=":memory:", bookings_db=":memory:"):
        self.apartments_repo = ApartmentRepo(apartments_db)
        self.bookings_repo = BookingRepo(bookings_db)
        self.apartments = ApartmentService(self.apartments_repo, BookingsLink(self.bookings_repo))
        self.bookings = BookingService(self.bookings_repo, self.apartments)
        self.relays = [
            Relay(self.apartments_repo.outbox, LocalPublisher(partial(handle_event, self.bookings_repo))),
            Relay(self.bookings_repo.outbox, LocalPublisher(partial(handle_booking_event, self.apartments_repo))),
        ]
        self.deliver()

    def deliver(self):
        for relay in self.relays:
            relay.publish_pending()

    def _delivering(self, method, *args, **kwargs):
        result = method(*args, **kwargs)
        self.deliver()
        return result

    def add_apartment(self, *args, **kwargs):
        return self._delivering(self.apartments.add, *args, **kwargs)

    def get_apartment(self, apt_id):
        return self.apartments.get(apt_id)

    def list_apartments(self):
        return self.apartments.list()

    def update_apartment(self, *args, **kwargs):
        return self._delivering(self.apartments.update, *args, **kwargs)

    def remove_apartment(self, apt_id):
        return self._delivering(self.apartments.delete, apt_id)

    def search_available(self, *args, **kwargs):
        return self.apartments.search_available(*args, **kwargs)

    def create_booking(self, *args, **kwargs):
        return self._delivering(self.bookings.create_booking, *args, **kwargs)

    def get_booking(self, booking_id):
        return self.bookings.get_booking(booking_id)

    def list_bookings(self, *args, **kwargs):
        return self.bookings.list_bookings(*args, **kwargs)

    def change_booking(self, *args, **kwargs):
        return self._delivering(self.bookings.change_booking, *args, **kwargs)

    def cancel_booking(self, booking_id):
        return self._delivering(self.bookings.cancel_booking, booking_id)

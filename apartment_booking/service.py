"""Business logic for apartments and bookings.

Date ranges are half-open: [check_in, check_out). A booking checking out on
the same day another checks in does not overlap with it.

BookingService owns bookings. It reaches apartments through an object with
get/list/add/update/delete: either the apartments service in the same process
(inprocess.LocalApartments), or HttpApartments, which calls it over HTTP.

The booking rules (does the apartment exist, which apartments are free) read
the local apartments replica, which events keep up to date, so they keep
working while the apartments service is down. The replica may lag behind by a
moment; see documentation/microservices-plan.md.
"""
from __future__ import annotations

from datetime import date

from common.errors import (BookingError, ConflictError, NotFoundError, OverlapError,
                           ServiceUnavailableError)

from .repos import BookingRepo

__all__ = ["ACTIVE", "CANCELLED", "BookingError", "BookingService", "ConflictError",
           "NotFoundError", "OverlapError", "ServiceUnavailableError", "open_service", "parse_date"]

ACTIVE = "active"
CANCELLED = "cancelled"


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise BookingError(f"Invalid date '{value}', expected YYYY-MM-DD") from None


def _validate_range(check_in: date, check_out: date) -> None:
    if check_out <= check_in:
        raise BookingError("Check-out date must be after check-in date")


class BookingService:
    def __init__(self, bookings: BookingRepo, apartments):
        self.bookings = bookings
        self.apartments = apartments

    # ---------- apartments ----------

    def add_apartment(self, name: str, address: str, rooms: int = 1, price: float = 0.0) -> dict:
        return self.apartments.add(name, address, rooms, price)

    def get_apartment(self, apt_id: int) -> dict:
        return self.apartments.get(apt_id)

    def list_apartments(self) -> list[dict]:
        return self.apartments.list()

    def update_apartment(self, apt_id: int, name=None, address=None, rooms=None, price=None) -> dict:
        return self.apartments.update(apt_id, name, address, rooms, price)

    def remove_apartment(self, apt_id: int) -> dict:
        # Check, then delete: the two live in different databases, so this can't
        # be one transaction. Accepted; see documentation/microservices-plan.md.
        apt = self.apartments.get(apt_id)
        with self.bookings.reading() as table:
            active = table.list(apt_id=apt_id)
        if active:
            ids = ", ".join(str(b["id"]) for b in active)
            raise ConflictError(
                f"Apartment {apt_id} has active bookings ({ids}); cancel them first")
        self.apartments.delete(apt_id)
        return apt

    # ---------- bookings ----------

    def create_booking(self, apt_id: int, guest: str, check_in: str, check_out: str) -> dict:
        guest = (guest or "").strip()
        d_in, d_out = parse_date(check_in), parse_date(check_out)
        _validate_range(d_in, d_out)
        self._require_apartment(apt_id)
        with self.bookings.writing() as table:
            self._ensure_no_overlap(table, apt_id, d_in, d_out)
            return table.insert(apt_id, guest, d_in.isoformat(), d_out.isoformat(), ACTIVE)

    def get_booking(self, booking_id: int) -> dict:
        with self.bookings.reading() as table:
            return self._booking(table, booking_id)

    def list_bookings(self, apt_id=None, guest=None, include_cancelled=False) -> list[dict]:
        with self.bookings.reading() as table:
            result = table.list(apt_id=apt_id, include_cancelled=include_cancelled)
        if guest is not None:
            result = [b for b in result if b["guest"].lower() == guest.lower()]
        return result

    def change_booking(self, booking_id: int, apt_id=None, guest=None,
                       check_in=None, check_out=None) -> dict:
        if apt_id is not None:
            # Outside the transaction: it may call the apartments service.
            self._require_apartment(apt_id)
        with self.bookings.writing() as table:
            booking = self._booking(table, booking_id)
            if booking["status"] != ACTIVE:
                raise ConflictError(f"Booking {booking_id} is cancelled and cannot be changed")
            new_apt = booking["apartment_id"] if apt_id is None else apt_id
            d_in = parse_date(check_in if check_in is not None else booking["check_in"])
            d_out = parse_date(check_out if check_out is not None else booking["check_out"])
            _validate_range(d_in, d_out)
            self._ensure_no_overlap(table, new_apt, d_in, d_out, ignore_id=booking_id)
            changes = {"apartment_id": new_apt, "check_in": d_in.isoformat(), "check_out": d_out.isoformat()}
            if guest is not None:
                changes["guest"] = guest.strip()
            return table.update(booking_id, **changes)

    def cancel_booking(self, booking_id: int) -> dict:
        with self.bookings.writing() as table:
            booking = self._booking(table, booking_id)
            if booking["status"] == CANCELLED:
                raise ConflictError(f"Booking {booking_id} is already cancelled")
            return table.update(booking_id, status=CANCELLED)

    # ---------- search ----------

    def search_available(self, check_in: str, check_out: str, min_rooms: int = 1) -> list[dict]:
        d_in, d_out = parse_date(check_in), parse_date(check_out)
        _validate_range(d_in, d_out)
        with self.bookings.reading() as table:
            return table.available_apartments(d_in.isoformat(), d_out.isoformat(), min_rooms)

    # ---------- helpers ----------

    def _require_apartment(self, apt_id: int) -> None:
        """Raise NotFoundError unless the apartment exists, preferring the replica.

        An apartment the replica hasn't heard of yet (created a moment ago) is
        fetched from the apartments service and added to the replica; its
        events will then bring it up to date.
        """
        with self.bookings.reading() as table:
            known = table.replica_get(apt_id)
        if known is not None:
            if known["deleted"]:
                raise NotFoundError(f"Apartment {apt_id} not found")
            return
        apt = self.apartments.get(apt_id)
        with self.bookings.writing() as table:
            table.replica_put(apt, version=0, only_if_missing=True)

    @staticmethod
    def _booking(table, booking_id: int) -> dict:
        booking = table.get(booking_id)
        if booking is None:
            raise NotFoundError(f"Booking {booking_id} not found")
        return booking

    @staticmethod
    def _ensure_no_overlap(table, apt_id, d_in, d_out, ignore_id=None) -> None:
        b = table.first_overlap(apt_id, d_in.isoformat(), d_out.isoformat(), ignore_id)
        if b is not None:
            raise OverlapError(
                f"Apartment {apt_id} is already booked from {b['check_in']} "
                f"to {b['check_out']} (booking {b['id']})")


def open_service(apartments_db: str = ":memory:", bookings_db: str = ":memory:",
                 apartments_url: str | None = None) -> BookingService:
    """Build the booking service on its SQLite database.

    With apartments_url, apartments come from the apartments service over HTTP.
    and the replica is fed by the booking consumer (consumer.py) from RabbitMQ.
    Without it, the apartments service runs in this process on apartments_db
    and delivers its events directly, which keeps tests and a plain
    `flask run` down to one process. The defaults keep everything in memory.
    """
    bookings = BookingRepo(bookings_db)
    if apartments_url:
        from .apartments_client import HttpApartments
        apartments = HttpApartments(apartments_url)
    else:
        from apartments_service.relay import Relay
        from apartments_service.repo import ApartmentRepo
        from apartments_service.service import ApartmentService

        from .inprocess import LocalApartments, LocalPublisher
        repo = ApartmentRepo(apartments_db)
        apartments = LocalApartments(ApartmentService(repo), Relay(repo.outbox, LocalPublisher(bookings)))
    return BookingService(bookings, apartments)

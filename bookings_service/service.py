"""Business rules for bookings.

Date ranges are half-open: [check_in, check_out). A booking checking out on
the same day another checks in does not overlap with it.

Whether the apartment of a booking exists is checked against the apartments
replica in bookings.db, which apartment events keep up to date, so booking
keeps working while the apartments service is down. An apartment the replica
hasn't heard of yet is looked up in the apartments service (`apartments`:
HttpApartments, or anything else with get()).
"""
from __future__ import annotations

from common.dates import parse_date, validate_range
from common.errors import (BookingError, ConflictError, NotFoundError, OverlapError,
                           ServiceUnavailableError)

from .repos import BookingRepo

__all__ = ["ACTIVE", "CANCELLED", "BookingError", "BookingService", "ConflictError",
           "NotFoundError", "OverlapError", "ServiceUnavailableError", "open_service", "parse_date"]

ACTIVE = "active"
CANCELLED = "cancelled"


class BookingService:
    def __init__(self, bookings: BookingRepo, apartments):
        self.bookings = bookings
        self.apartments = apartments

    def create_booking(self, apt_id: int, guest: str, check_in: str, check_out: str) -> dict:
        guest = (guest or "").strip()
        d_in, d_out = parse_date(check_in), parse_date(check_out)
        validate_range(d_in, d_out)
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
            validate_range(d_in, d_out)
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


def open_service(bookings_db: str, apartments_url: str) -> BookingService:
    """The booking service on its database, reaching apartments over HTTP.

    Events travel through RabbitMQ (worker.py), or through devstack/ when
    running without Docker.
    """
    from .apartments_client import HttpApartments
    return BookingService(BookingRepo(bookings_db), HttpApartments(apartments_url))

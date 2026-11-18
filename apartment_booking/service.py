"""Business logic for apartments and bookings.

Date ranges are half-open: [check_in, check_out). A booking checking out on
the same day another checks in does not overlap with it.

ApartmentService owns apartments. BookingService owns bookings and reaches
apartments only through ApartmentService's methods, so apartments can later
move into their own service without changing the booking rules.
"""
from __future__ import annotations

from datetime import date

from .errors import BookingError, ConflictError, NotFoundError, OverlapError
from .repos import ApartmentRepo, BookingRepo

__all__ = ["ACTIVE", "CANCELLED", "ApartmentService", "BookingError", "BookingService",
           "ConflictError", "NotFoundError", "OverlapError", "open_service", "parse_date"]

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


class ApartmentService:
    def __init__(self, repo: ApartmentRepo):
        self.repo = repo

    def add(self, name: str, address: str, rooms: int = 1, price: float = 0.0) -> dict:
        name = (name or "").strip()
        if not name:
            raise BookingError("Apartment name is required")
        if rooms < 1:
            raise BookingError("Rooms must be at least 1")
        if price < 0:
            raise BookingError("Price cannot be negative")
        return self.repo.add(name, address or "", rooms, price)

    def get(self, apt_id: int) -> dict:
        apt = self.repo.get(apt_id)
        if apt is None:
            raise NotFoundError(f"Apartment {apt_id} not found")
        return apt

    def list(self) -> list[dict]:
        return self.repo.list()

    def update(self, apt_id: int, name=None, address=None, rooms=None, price=None) -> dict:
        self.get(apt_id)
        changes = {}
        if name is not None:
            if not name.strip():
                raise BookingError("Apartment name cannot be empty")
            changes["name"] = name.strip()
        if address is not None:
            changes["address"] = address
        if rooms is not None:
            if rooms < 1:
                raise BookingError("Rooms must be at least 1")
            changes["rooms"] = rooms
        if price is not None:
            if price < 0:
                raise BookingError("Price cannot be negative")
            changes["price"] = price
        apt = self.repo.update(apt_id, **changes)
        if apt is None:
            raise NotFoundError(f"Apartment {apt_id} not found")
        return apt

    def delete(self, apt_id: int) -> dict:
        apt = self.get(apt_id)
        if not self.repo.delete(apt_id):
            raise NotFoundError(f"Apartment {apt_id} not found")
        return apt


class BookingService:
    def __init__(self, bookings: BookingRepo, apartments: ApartmentService):
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
        self.apartments.get(apt_id)
        with self.bookings.reading() as table:
            active = table.list(apt_id=apt_id)
        if active:
            ids = ", ".join(str(b["id"]) for b in active)
            raise ConflictError(
                f"Apartment {apt_id} has active bookings ({ids}); cancel them first")
        return self.apartments.delete(apt_id)

    # ---------- bookings ----------

    def create_booking(self, apt_id: int, guest: str, check_in: str, check_out: str) -> dict:
        guest = (guest or "").strip()
        d_in, d_out = parse_date(check_in), parse_date(check_out)
        _validate_range(d_in, d_out)
        self.apartments.get(apt_id)
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
            # Outside the transaction: it may become a call to another service.
            self.apartments.get(apt_id)
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
            busy = table.busy_apartments(d_in.isoformat(), d_out.isoformat())
        return [a for a in self.apartments.list()
                if a["id"] not in busy and a["rooms"] >= min_rooms]

    # ---------- helpers ----------

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


def open_service(apartments_db: str = ":memory:", bookings_db: str = ":memory:") -> BookingService:
    """Build the service on two SQLite databases; the defaults keep everything in memory."""
    return BookingService(BookingRepo(bookings_db), ApartmentService(ApartmentRepo(apartments_db)))

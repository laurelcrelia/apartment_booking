"""Business logic for apartments and bookings.

Date ranges are half-open: [check_in, check_out). A booking checking out on
the same day another checks in does not overlap with it.
"""
from __future__ import annotations

from datetime import date

ACTIVE = "active"
CANCELLED = "cancelled"


class BookingError(Exception):
    """Raised for any invalid operation; the message is shown to the user."""


class NotFoundError(BookingError):
    pass


class OverlapError(BookingError):
    pass


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise BookingError(f"Invalid date '{value}', expected YYYY-MM-DD") from None


def _validate_range(check_in: date, check_out: date) -> None:
    if check_out <= check_in:
        raise BookingError("Check-out date must be after check-in date")


def _overlaps(a_in: date, a_out: date, b_in: date, b_out: date) -> bool:
    return a_in < b_out and b_in < a_out


class BookingService:
    def __init__(self, storage):
        self.storage = storage

    # ---------- apartments ----------

    def add_apartment(self, name: str, address: str, rooms: int = 1, price: float = 0.0) -> dict:
        name = (name or "").strip()
        if not name:
            raise BookingError("Apartment name is required")
        if rooms < 1:
            raise BookingError("Rooms must be at least 1")
        if price < 0:
            raise BookingError("Price cannot be negative")
        state = self.storage.load()
        apt_id = state["next_apartment_id"]
        apt = {"id": apt_id, "name": name, "address": address or "", "rooms": rooms, "price": price}
        state["apartments"][str(apt_id)] = apt
        state["next_apartment_id"] = apt_id + 1
        self.storage.save(state)
        return apt

    def get_apartment(self, apt_id: int) -> dict:
        state = self.storage.load()
        return self._apartment(state, apt_id)

    def list_apartments(self) -> list[dict]:
        state = self.storage.load()
        return sorted(state["apartments"].values(), key=lambda a: a["id"])

    def update_apartment(self, apt_id: int, name=None, address=None, rooms=None, price=None) -> dict:
        state = self.storage.load()
        apt = self._apartment(state, apt_id)
        if name is not None:
            if not name.strip():
                raise BookingError("Apartment name cannot be empty")
            apt["name"] = name.strip()
        if address is not None:
            apt["address"] = address
        if rooms is not None:
            if rooms < 1:
                raise BookingError("Rooms must be at least 1")
            apt["rooms"] = rooms
        if price is not None:
            if price < 0:
                raise BookingError("Price cannot be negative")
            apt["price"] = price
        self.storage.save(state)
        return apt

    def remove_apartment(self, apt_id: int) -> dict:
        state = self.storage.load()
        apt = self._apartment(state, apt_id)
        active = [b for b in state["bookings"].values()
                  if b["apartment_id"] == apt_id and b["status"] == ACTIVE]
        if active:
            ids = ", ".join(str(b["id"]) for b in active)
            raise BookingError(
                f"Apartment {apt_id} has active bookings ({ids}); cancel them first")
        del state["apartments"][str(apt_id)]
        self.storage.save(state)
        return apt

    # ---------- bookings ----------

    def create_booking(self, apt_id: int, guest: str, check_in: str, check_out: str) -> dict:
        guest = (guest or "").strip()
        d_in, d_out = parse_date(check_in), parse_date(check_out)
        _validate_range(d_in, d_out)
        state = self.storage.load()
        self._apartment(state, apt_id)
        self._ensure_no_overlap(state, apt_id, d_in, d_out)
        b_id = state["next_booking_id"]
        booking = {
            "id": b_id,
            "apartment_id": apt_id,
            "guest": guest,
            "check_in": d_in.isoformat(),
            "check_out": d_out.isoformat(),
            "status": ACTIVE,
        }
        state["bookings"][str(b_id)] = booking
        state["next_booking_id"] = b_id + 1
        self.storage.save(state)
        return booking

    def get_booking(self, booking_id: int) -> dict:
        state = self.storage.load()
        return self._booking(state, booking_id)

    def list_bookings(self, apt_id=None, guest=None, include_cancelled=False) -> list[dict]:
        state = self.storage.load()
        result = []
        for b in state["bookings"].values():
            if apt_id is not None and b["apartment_id"] != apt_id:
                continue
            if guest is not None and b["guest"].lower() != guest.lower():
                continue
            if not include_cancelled and b["status"] != ACTIVE:
                continue
            result.append(b)
        return sorted(result, key=lambda b: (b["check_in"], b["id"]))

    def change_booking(self, booking_id: int, apt_id=None, guest=None,
                       check_in=None, check_out=None) -> dict:
        state = self.storage.load()
        booking = self._booking(state, booking_id)
        if booking["status"] != ACTIVE:
            raise BookingError(f"Booking {booking_id} is cancelled and cannot be changed")
        new_apt = booking["apartment_id"] if apt_id is None else apt_id
        d_in = parse_date(check_in if check_in is not None else booking["check_in"])
        d_out = parse_date(check_out if check_out is not None else booking["check_out"])
        _validate_range(d_in, d_out)
        self._apartment(state, new_apt)
        self._ensure_no_overlap(state, new_apt, d_in, d_out, ignore_id=booking_id)
        if guest is not None:
            booking["guest"] = guest.strip()
        booking.update(apartment_id=new_apt, check_in=d_in.isoformat(), check_out=d_out.isoformat())
        self.storage.save(state)
        return booking

    def cancel_booking(self, booking_id: int) -> dict:
        state = self.storage.load()
        booking = self._booking(state, booking_id)
        if booking["status"] == CANCELLED:
            raise BookingError(f"Booking {booking_id} is already cancelled")
        booking["status"] = CANCELLED
        self.storage.save(state)
        return booking

    # ---------- search ----------

    def search_available(self, check_in: str, check_out: str, min_rooms: int = 1) -> list[dict]:
        d_in, d_out = parse_date(check_in), parse_date(check_out)
        _validate_range(d_in, d_out)
        state = self.storage.load()
        busy = {
            b["apartment_id"] for b in state["bookings"].values()
            if b["status"] == ACTIVE and _overlaps(
                d_in, d_out, parse_date(b["check_in"]), parse_date(b["check_out"]))
        }
        return sorted(
            (a for a in state["apartments"].values()
             if a["id"] not in busy and a["rooms"] >= min_rooms),
            key=lambda a: a["id"],
        )

    # ---------- helpers ----------

    @staticmethod
    def _apartment(state: dict, apt_id: int) -> dict:
        try:
            return state["apartments"][str(apt_id)]
        except KeyError:
            raise NotFoundError(f"Apartment {apt_id} not found") from None

    @staticmethod
    def _booking(state: dict, booking_id: int) -> dict:
        try:
            return state["bookings"][str(booking_id)]
        except KeyError:
            raise NotFoundError(f"Booking {booking_id} not found") from None

    @staticmethod
    def _ensure_no_overlap(state, apt_id, d_in, d_out, ignore_id=None) -> None:
        for b in state["bookings"].values():
            if b["id"] == ignore_id or b["apartment_id"] != apt_id or b["status"] != ACTIVE:
                continue
            if _overlaps(d_in, d_out, parse_date(b["check_in"]), parse_date(b["check_out"])):
                raise OverlapError(
                    f"Apartment {apt_id} is already booked from {b['check_in']} "
                    f"to {b['check_out']} (booking {b['id']})")

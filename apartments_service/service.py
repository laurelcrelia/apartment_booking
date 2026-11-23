"""Business rules for apartments.

Two rules need booking data, which belongs to the booking service:

- availability search reads the bookings replica in apartments.db, which the
  booking service's events keep up to date (it may lag a moment behind);
- deleting an apartment asks the booking service for active bookings first,
  so that rule stays strict. `bookings` is that link: HttpBookings, or the
  booking repository itself when both run in one process.
"""
from __future__ import annotations

from common.dates import parse_range
from common.errors import BookingError, ConflictError, NotFoundError

from .repo import ApartmentRepo


class ApartmentService:
    def __init__(self, repo: ApartmentRepo, bookings):
        self.repo = repo
        self.bookings = bookings

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
        # Check, then delete: the bookings live in another service, so this
        # can't be one transaction. Accepted; see documentation/gateway-plan.md.
        active = self.bookings.active_bookings(apt_id)
        if active:
            ids = ", ".join(str(b["id"]) for b in active)
            raise ConflictError(f"Apartment {apt_id} has active bookings ({ids}); cancel them first")
        if not self.repo.delete(apt_id):
            raise NotFoundError(f"Apartment {apt_id} not found")
        return apt

    def search_available(self, check_in: str, check_out: str, min_rooms: int = 1) -> list[dict]:
        d_in, d_out = parse_range(check_in, check_out)
        return self.repo.available(d_in.isoformat(), d_out.isoformat(), min_rooms)

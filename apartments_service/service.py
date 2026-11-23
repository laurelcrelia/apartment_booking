"""Business rules for apartments."""
from __future__ import annotations

from common.errors import BookingError, NotFoundError

from .repo import ApartmentRepo


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

"""HTTP client for the apartments service.

Has the same methods as apartments_service.service.ApartmentService, so
BookingService works with either.
"""
from __future__ import annotations

from common.client import ServiceClient


class HttpApartments(ServiceClient):
    name = "apartments"

    def add(self, name: str, address: str, rooms: int = 1, price: float = 0.0) -> dict:
        return self.call("POST", "/api/apartments",
                         {"name": name, "address": address, "rooms": rooms, "price": price})

    def get(self, apt_id: int) -> dict:
        return self.call("GET", f"/api/apartments/{apt_id}")

    def list(self) -> list[dict]:
        return self.call("GET", "/api/apartments")

    def update(self, apt_id: int, name=None, address=None, rooms=None, price=None) -> dict:
        changes = {"name": name, "address": address, "rooms": rooms, "price": price}
        return self.call("PATCH", f"/api/apartments/{apt_id}",
                         {k: v for k, v in changes.items() if v is not None})

    def delete(self, apt_id: int) -> None:
        self.call("DELETE", f"/api/apartments/{apt_id}")

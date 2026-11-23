"""HTTP client for the booking service, used for the delete check."""
from __future__ import annotations

from common.client import ServiceClient


class HttpBookings(ServiceClient):
    name = "booking"

    def active_bookings(self, apt_id: int) -> list[dict]:
        """The apartment's active bookings, as the booking service knows them right now."""
        return self.call("GET", "/api/bookings", query={"apartment_id": apt_id})

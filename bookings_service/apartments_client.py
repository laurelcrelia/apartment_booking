"""HTTP client for the apartments service: the booking service only needs to look
an apartment up when its replica doesn't know it yet."""
from __future__ import annotations

from common.client import ServiceClient


class HttpApartments(ServiceClient):
    name = "apartments"

    def get(self, apt_id: int) -> dict:
        return self.call("GET", f"/api/apartments/{apt_id}")

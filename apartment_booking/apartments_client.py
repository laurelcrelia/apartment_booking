"""HTTP client for the apartments service.

Has the same methods as apartments_service.service.ApartmentService, so
BookingService works with either. Errors from the apartments service come back
as the same exceptions the in-process service raises; if the service can't be
reached or fails, ServiceUnavailableError is raised (HTTP 503 to our clients).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from common.errors import BookingError, ConflictError, NotFoundError, ServiceUnavailableError

UNAVAILABLE = "The apartments service is unavailable; try again later"


class HttpApartments:
    def __init__(self, base_url: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def add(self, name: str, address: str, rooms: int = 1, price: float = 0.0) -> dict:
        return self._call("POST", "/api/apartments",
                          {"name": name, "address": address, "rooms": rooms, "price": price})

    def get(self, apt_id: int) -> dict:
        return self._call("GET", f"/api/apartments/{apt_id}")

    def list(self) -> list[dict]:
        return self._call("GET", "/api/apartments")

    def update(self, apt_id: int, name=None, address=None, rooms=None, price=None) -> dict:
        changes = {"name": name, "address": address, "rooms": rooms, "price": price}
        return self._call("PATCH", f"/api/apartments/{apt_id}",
                          {k: v for k, v in changes.items() if v is not None})

    def delete(self, apt_id: int) -> None:
        self._call("DELETE", f"/api/apartments/{apt_id}")

    def _call(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as e:
            with e:
                raise self._error(e.code, e.read()) from None
        except OSError:  # connection refused, DNS failure, timeout, ...
            raise ServiceUnavailableError(UNAVAILABLE) from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise ServiceUnavailableError(UNAVAILABLE) from None

    @staticmethod
    def _error(status: int, raw: bytes) -> BookingError:
        if status >= 500:
            return ServiceUnavailableError(UNAVAILABLE)
        try:
            message = json.loads(raw)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = f"Apartments service returned HTTP {status}"
        if status == 404:
            return NotFoundError(message)
        if status == 409:
            return ConflictError(message)
        return BookingError(message)

"""Base for HTTP clients that one service uses to call another.

Errors from the other service come back as the same exceptions an in-process
call would raise; if the service can't be reached or fails,
ServiceUnavailableError is raised (HTTP 503 to our own clients).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .errors import BookingError, ConflictError, NotFoundError, ServiceUnavailableError


class ServiceClient:
    name = "remote"  # used in the "unavailable" message

    def __init__(self, base_url: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def unavailable(self) -> str:
        return f"The {self.name} service is unavailable; try again later"

    def call(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        url = self.base_url + path + ("?" + urlencode(query) if query else "")
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as e:
            with e:
                raise self._error(e.code, e.read()) from None
        except OSError:  # connection refused, DNS failure, timeout, ...
            raise ServiceUnavailableError(self.unavailable) from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise ServiceUnavailableError(self.unavailable) from None

    def _error(self, status: int, raw: bytes) -> BookingError:
        if status >= 500:
            return ServiceUnavailableError(self.unavailable)
        try:
            message = json.loads(raw)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = f"The {self.name} service returned HTTP {status}"
        if status == 404:
            return NotFoundError(message)
        if status == 409:
            return ConflictError(message)
        return BookingError(message)

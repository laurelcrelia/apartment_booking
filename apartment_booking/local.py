"""Both services in one process, behind a small Python stand-in for the NGINX gateway.

For development without Docker, and for the tests:

    python -m apartment_booking.local [--port 8000]

Data is kept in ./apartments.db and ./bookings.db (APARTMENTS_DB, BOOKINGS_DB).
Requests are routed by path exactly like nginx/default.conf: /api/apartments
to the apartments service, everything else to the web app. Keep the two in
sync; CI runs the same API tests against the real gateway.
"""
from __future__ import annotations

import argparse
import os

from apartments_service.app import create_app as create_apartments_app

from .service import BookingService, open_service
from .web import create_app as create_web_app

APARTMENTS_PREFIX = "/api/apartments"


def routes_to_apartments(path: str) -> bool:
    return path == APARTMENTS_PREFIX or path.startswith(APARTMENTS_PREFIX + "/")


class LocalGateway:
    """A WSGI app that hands each request to the service that owns its path."""

    def __init__(self, web_app, apartments_app):
        self.web_app = web_app
        self.apartments_app = apartments_app

    def __call__(self, environ, start_response):
        app = self.apartments_app if routes_to_apartments(environ.get("PATH_INFO", "")) else self.web_app
        return app(environ, start_response)


def create_local_app(service: BookingService | None = None) -> LocalGateway:
    """The gateway over both services, sharing one in-process service.

    Without a service, the databases come from $APARTMENTS_DB and $BOOKINGS_DB
    (default: apartments.db and bookings.db).
    """
    if service is None:
        service = open_service(os.environ.get("APARTMENTS_DB", "apartments.db"),
                               os.environ.get("BOOKINGS_DB", "bookings.db"))
    apartment_service = getattr(service.apartments, "service", None)
    if apartment_service is None:
        raise ValueError("create_local_app needs an in-process service (open_service without apartments_url)")
    return LocalGateway(create_web_app(service), create_apartments_app(apartment_service))


def main(argv=None) -> None:  # pragma: no cover - starts a server
    from werkzeug.serving import run_simple

    p = argparse.ArgumentParser(prog="python -m apartment_booking.local",
                                description="Run both services locally behind a stand-in gateway.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    run_simple(args.host, args.port, create_local_app(), threaded=True)


if __name__ == "__main__":  # pragma: no cover
    main()

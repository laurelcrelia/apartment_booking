"""The booking service's web app: the REST API for bookings (api.py).

The pages are static files in frontend/, served by the gateway (NGINX, or
apartment_booking/local.py without Docker), and load their data from the API.

Run locally:   python -m apartment_booking.local --port 8000   (everything together)
Run in Docker: docker compose up -d --build --wait
"""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common.http import handle_http_error, trust_proxies

from .api import api
from .service import BookingService, open_service


def create_app(service: BookingService | None = None) -> Flask:
    """Build the app; without a service it is configured from the environment:

    BOOKINGS_DB     bookings database (default: bookings.db)
    APARTMENTS_URL  apartments service, e.g. http://apartments:8000; if unset,
                    apartments are served in-process from APARTMENTS_DB
                    (default: apartments.db)
    TRUSTED_PROXIES number of reverse proxies in front of the app (default 0);
                    their X-Forwarded-* headers are trusted, so the app sees the
                    real client. Only set it when the app is reachable solely
                    through those proxies, or clients could fake their address.
    """
    app = Flask(__name__, static_folder=None)  # the frontend is served by the gateway
    if service is None:
        service = open_service(os.environ.get("APARTMENTS_DB", "apartments.db"),
                               os.environ.get("BOOKINGS_DB", "bookings.db"),
                               os.environ.get("APARTMENTS_URL"))
    app.extensions["booking_service"] = service
    trust_proxies(app)
    app.register_blueprint(api)
    app.register_error_handler(HTTPException, handle_http_error)
    return app

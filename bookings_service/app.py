"""Booking service: the REST API for bookings (api.py), behind the NGINX gateway.

It owns bookings and their database, and asks the apartments service over
HTTP about apartments its replica doesn't know yet (see service.py).

Run locally:   python -m devstack --port 8000   (everything together)
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
    APARTMENTS_URL  apartments service, e.g. http://apartments:8000 (required)
    TRUSTED_PROXIES number of reverse proxies in front of the app (default 0);
                    their X-Forwarded-* headers are trusted, so the app sees the
                    real client. Only set it when the app is reachable solely
                    through those proxies, or clients could fake their address.
    """
    app = Flask(__name__, static_folder=None)  # the frontend is served by the gateway
    if service is None:
        apartments_url = os.environ.get("APARTMENTS_URL")
        if not apartments_url:
            raise RuntimeError("Set APARTMENTS_URL to the apartments service, e.g. http://apartments:8000")
        service = open_service(os.environ.get("BOOKINGS_DB", "bookings.db"), apartments_url)
    app.extensions["booking_service"] = service
    trust_proxies(app)
    app.register_blueprint(api)
    app.register_error_handler(HTTPException, handle_http_error)
    return app

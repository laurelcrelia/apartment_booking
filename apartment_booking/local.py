"""Both services in one process, behind a small Python stand-in for the NGINX gateway.

For development without Docker, and for the tests:

    python -m apartment_booking.local [--port 8000]

Data is kept in ./apartments.db and ./bookings.db (APARTMENTS_DB, BOOKINGS_DB).
Requests are routed by path exactly like nginx/default.conf: /api/apartments
to the apartments service, the rest of /api to the web app, and everything
else to the static frontend in frontend/. Keep the two in sync; CI runs the
API tests and the smoke test against the real gateway.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
from pathlib import Path

from werkzeug.wrappers import Response

from apartments_service.app import create_app as create_apartments_app

from .service import BookingService, open_service
from .web import create_app as create_web_app

APARTMENTS_PREFIX = "/api/apartments"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
# Set explicitly: mimetypes' answers differ between Python versions.
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}

# Page URLs and the static file that renders each, like the nginx locations.
PAGES = [
    (re.compile(r"/"), "index.html"),
    (re.compile(r"/apartments/\d+"), "apartment.html"),
    (re.compile(r"/bookings"), "bookings.html"),
    (re.compile(r"/bookings/\d+"), "booking.html"),
    (re.compile(r"/api/docs"), "api-docs.html"),
]


def routes_to_apartments(path: str) -> bool:
    return path == APARTMENTS_PREFIX or path.startswith(APARTMENTS_PREFIX + "/")


def frontend_file(path: str) -> Path | None:
    """The file in frontend/ for a page URL or a /static/ file, or None."""
    for pattern, page in PAGES:
        if pattern.fullmatch(path):
            return FRONTEND_DIR / page
    if path.startswith("/static/"):
        file = (FRONTEND_DIR / path.lstrip("/")).resolve()
        if file.is_relative_to(FRONTEND_DIR / "static") and file.is_file():
            return file
    return None


def serve_frontend(environ, start_response):
    file = frontend_file(environ.get("PATH_INFO", ""))
    status = 200
    if file is None:
        file, status = FRONTEND_DIR / "404.html", 404
    content_type = CONTENT_TYPES.get(file.suffix) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return Response(file.read_bytes(), status=status, content_type=content_type)(environ, start_response)


class LocalGateway:
    """A WSGI app that hands each request to the service or file that owns its path."""

    def __init__(self, web_app, apartments_app):
        self.web_app = web_app
        self.apartments_app = apartments_app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if routes_to_apartments(path):
            app = self.apartments_app
        elif path.startswith("/api/") and path != "/api/docs":
            app = self.web_app
        else:
            app = serve_frontend
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

"""A small Python stand-in for the NGINX gateway.

Routes requests by path exactly like nginx/default.conf: /api/apartments to
the apartments service, the rest of /api to the booking service, and
everything else to the static frontend in frontend/. Keep the two in sync (a
unit test compares the page routes); CI runs the API tests and the smoke
test against the real gateway.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from werkzeug.wrappers import Response

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


class Gateway:
    """A WSGI app that hands each request to the service or file that owns its path.

    after_write, if given, is called after every API request that may change
    data, once the response is complete (devstack delivers events with it).
    """

    def __init__(self, bookings_app, apartments_app, after_write=None):
        self.bookings_app = bookings_app
        self.apartments_app = apartments_app
        self.after_write = after_write

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if routes_to_apartments(path):
            app = self.apartments_app
        elif path.startswith("/api/") and path != "/api/docs":
            app = self.bookings_app
        else:
            return serve_frontend(environ, start_response)
        if self.after_write is None or environ.get("REQUEST_METHOD") in ("GET", "HEAD"):
            return app(environ, start_response)
        response = app(environ, start_response)
        try:
            body = list(response)
        finally:
            getattr(response, "close", lambda: None)()
        self.after_write()
        return body

"""Web application: HTML pages with forms, plus the REST API from api.py.

Run locally:   flask --app apartment_booking.web run --port 8000
Run in Docker: docker compose up -d --build --wait
"""
from __future__ import annotations

import os
import threading
from datetime import date

from flask import Blueprint, Flask, abort, current_app, render_template, request
from werkzeug.exceptions import HTTPException

from .api import api, handle_http_error
from .service import BookingService, NotFoundError
from .storage import JsonStorage

pages = Blueprint("pages", __name__)


class SerializedService:
    """Runs one service call at a time.

    Every service method loads the JSON file, changes it and saves it again,
    so concurrent requests must not interleave or updates could be lost.
    This only guards a single process: run the server with one worker.
    """

    def __init__(self, service: BookingService):
        self._service = service
        self._lock = threading.Lock()

    def __getattr__(self, name):
        method = getattr(self._service, name)

        def call(*args, **kwargs):
            with self._lock:
                return method(*args, **kwargs)
        return call


def create_app(storage=None) -> Flask:
    app = Flask(__name__)
    if storage is None:
        storage = JsonStorage(os.environ.get("APT_DATA_FILE", "data.json"))
    app.extensions["booking_service"] = SerializedService(BookingService(storage))
    app.register_blueprint(api)
    app.register_blueprint(pages)
    app.register_error_handler(HTTPException, handle_http_error)
    return app


def svc():
    return current_app.extensions["booking_service"]


@pages.app_template_filter("nights")
def nights(booking: dict) -> int:
    """Number of nights; check-out is exclusive."""
    return (date.fromisoformat(booking["check_out"]) - date.fromisoformat(booking["check_in"])).days


@pages.app_template_filter("money")
def money(value: float) -> str:
    return f"€{value:,.0f}" if float(value).is_integer() else f"€{value:,.2f}"


@pages.app_template_filter("nice_date")
def nice_date(value: str) -> str:
    d = date.fromisoformat(value)
    return f"{d:%b} {d.day}, {d.year}"


@pages.app_template_filter("initials")
def initials(name: str) -> str:
    return "".join(word[0] for word in name.split()[:2]).upper() or "?"


def _active_counts() -> dict[int, int]:
    counts: dict[int, int] = {}
    for b in svc().list_bookings():
        counts[b["apartment_id"]] = counts.get(b["apartment_id"], 0) + 1
    return counts


def _apartment_or_404(apartment_id: int) -> dict:
    try:
        return svc().get_apartment(apartment_id)
    except NotFoundError:
        abort(404)


@pages.get("/")
def apartments():
    return render_template("apartments.html", apartments=svc().list_apartments(),
                           active_counts=_active_counts())


@pages.get("/apartments/<int:apartment_id>")
def apartment(apartment_id: int):
    apt = _apartment_or_404(apartment_id)
    bookings = svc().list_bookings(apt_id=apartment_id, include_cancelled=True)
    return render_template("apartment.html", apartment=apt, bookings=bookings)


@pages.get("/bookings")
def bookings():
    apartment_id = request.args.get("apartment_id", "")
    guest = request.args.get("guest", "").strip()
    include_cancelled = request.args.get("include_cancelled") == "true"
    apts = svc().list_apartments()
    items = svc().list_bookings(
        apt_id=int(apartment_id) if apartment_id.isdigit() else None,
        guest=guest or None,
        include_cancelled=include_cancelled,
    )
    return render_template(
        "bookings.html", bookings=items, apartments=apts,
        apartments_by_id={a["id"]: a for a in apts},
        filters={"apartment_id": apartment_id, "guest": guest,
                 "include_cancelled": include_cancelled})


@pages.get("/bookings/<int:booking_id>")
def booking(booking_id: int):
    try:
        b = svc().get_booking(booking_id)
    except NotFoundError:
        abort(404)
    apts = svc().list_apartments()
    apt = next((a for a in apts if a["id"] == b["apartment_id"]), None)
    return render_template("booking.html", booking=b, apartment=apt, apartments=apts)


@pages.get("/api/docs")
def api_docs():
    return render_template("api_docs.html")

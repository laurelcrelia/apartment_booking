"""Web application: HTML pages with forms, plus the REST API from api.py.

Run locally:   flask --app apartment_booking.web run --port 8000
Run in Docker: docker compose up -d --build --wait
"""
from __future__ import annotations

import os
import threading

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


def _apartment_or_404(apartment_id: int) -> dict:
    try:
        return svc().get_apartment(apartment_id)
    except NotFoundError:
        abort(404)


@pages.get("/")
def apartments():
    return render_template("apartments.html", apartments=svc().list_apartments())


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
    items = svc().list_bookings(
        apt_id=int(apartment_id) if apartment_id.isdigit() else None,
        guest=guest or None,
        include_cancelled=include_cancelled,
    )
    return render_template(
        "bookings.html", bookings=items, apartments=svc().list_apartments(),
        filters={"apartment_id": apartment_id, "guest": guest,
                 "include_cancelled": include_cancelled})


@pages.get("/bookings/<int:booking_id>")
def booking(booking_id: int):
    try:
        b = svc().get_booking(booking_id)
    except NotFoundError:
        abort(404)
    return render_template("booking.html", booking=b, apartments=svc().list_apartments())


@pages.get("/api/docs")
def api_docs():
    return render_template("api_docs.html")

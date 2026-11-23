"""Apartments service: the public JSON API for apartments, behind the NGINX gateway.

It owns apartments and their database. For the two rules that need bookings
it keeps a bookings replica (availability search) and asks the booking
service over HTTP (the delete check); see service.py.

Run locally:   BOOKINGS_URL=http://localhost:8000 APARTMENTS_DB=apartments.db \
               flask --app apartments_service.app run --port 8001
Run in Docker: started by compose.yaml as the `apartments` service
"""
from __future__ import annotations

import os

from flask import Blueprint, Flask, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from common.http import (ApiError, created, handle_http_error, json_body, query_int,
                         register_error_handlers, trust_proxies)

from .bookings_client import HttpBookings
from .repo import ApartmentRepo
from .service import ApartmentService

api = Blueprint("apartments_api", __name__, url_prefix="/api")
register_error_handlers(api)

APARTMENT_FIELDS = {"name": str, "address": str, "rooms": int, "price": float}


def create_app(service: ApartmentService | None = None) -> Flask:
    """Build the app; without a service it is configured from the environment:

    APARTMENTS_DB   apartments database (default: apartments.db)
    BOOKINGS_URL    booking service, for the delete check (required)
    TRUSTED_PROXIES see common.http.trust_proxies
    """
    app = Flask(__name__)
    if service is None:
        bookings_url = os.environ.get("BOOKINGS_URL")
        if not bookings_url:
            raise RuntimeError("Set BOOKINGS_URL to the booking service, e.g. http://web:8000")
        service = ApartmentService(ApartmentRepo(os.environ.get("APARTMENTS_DB", "apartments.db")),
                                   HttpBookings(bookings_url))
    app.extensions["apartment_service"] = service
    trust_proxies(app)
    app.register_blueprint(api)
    app.register_error_handler(HTTPException, handle_http_error)
    return app


def svc() -> ApartmentService:
    return current_app.extensions["apartment_service"]


@api.get("/apartments")
def list_apartments():
    """All apartments, or with from and to, those free for that stay."""
    check_in, check_out = request.args.get("from"), request.args.get("to")
    min_rooms = query_int("min_rooms", minimum=1) or 1
    if (check_in is None) != (check_out is None):
        raise ApiError(400, "validation_error", "Query parameters 'from' and 'to' must be given together")
    if check_in is not None:
        return jsonify(svc().search_available(check_in, check_out, min_rooms))
    return jsonify([a for a in svc().list() if a["rooms"] >= min_rooms])


@api.post("/apartments")
def create_apartment():
    body = json_body(APARTMENT_FIELDS, required=("name", "address"))
    apt = svc().add(body["name"], body["address"],
                    rooms=body.get("rooms", 1), price=body.get("price", 0.0))
    return created(apt, "apartments_api.get_apartment", apartment_id=apt["id"])


@api.get("/apartments/<int:apartment_id>")
def get_apartment(apartment_id: int):
    return jsonify(svc().get(apartment_id))


@api.patch("/apartments/<int:apartment_id>")
def update_apartment(apartment_id: int):
    body = json_body(APARTMENT_FIELDS)
    return jsonify(svc().update(apartment_id, **body))


@api.delete("/apartments/<int:apartment_id>")
def delete_apartment(apartment_id: int):
    svc().delete(apartment_id)
    return "", 204


@api.get("/health")
def health():
    return jsonify(status="ok")

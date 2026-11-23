"""Apartments service: a JSON API for apartments, backed by its own SQLite database.

It knows nothing about bookings. The booking service (apartment_booking) calls
it over HTTP and stays the public entry point; this service is internal.

Run locally:   APARTMENTS_DB=apartments.db flask --app apartments_service.app run --port 8001
Run in Docker: started by compose.yaml as the `apartments` service
"""
from __future__ import annotations

import os

from flask import Blueprint, Flask, current_app, jsonify
from werkzeug.exceptions import HTTPException

from common.http import created, handle_http_error, json_body, query_int, register_error_handlers

from .repo import ApartmentRepo
from .service import ApartmentService

api = Blueprint("apartments_api", __name__, url_prefix="/api")
register_error_handlers(api)

APARTMENT_FIELDS = {"name": str, "address": str, "rooms": int, "price": float}


def create_app(service: ApartmentService | None = None) -> Flask:
    """Build the app; without a service it opens $APARTMENTS_DB (default: apartments.db)."""
    app = Flask(__name__)
    if service is None:
        service = ApartmentService(ApartmentRepo(os.environ.get("APARTMENTS_DB", "apartments.db")))
    app.extensions["apartment_service"] = service
    app.register_blueprint(api)
    app.register_error_handler(HTTPException, handle_http_error)
    return app


def svc() -> ApartmentService:
    return current_app.extensions["apartment_service"]


@api.get("/apartments")
def list_apartments():
    min_rooms = query_int("min_rooms", minimum=1) or 1
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

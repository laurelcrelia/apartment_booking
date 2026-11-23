"""REST API: JSON resources for apartments and bookings, mounted under /api.

The API contract is documented in openapi.yaml; keep the two in sync.
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from common.http import (ApiError, created, json_body, query_bool, query_int,
                         register_error_handlers)

from .service import CANCELLED

SPEC_PATH = Path(__file__).with_name("openapi.yaml")

api = Blueprint("api", __name__, url_prefix="/api")
register_error_handlers(api)


def svc():
    return current_app.extensions["booking_service"]


# ---------- apartments ----------

APARTMENT_FIELDS = {"name": str, "address": str, "rooms": int, "price": float}


@api.get("/apartments")
def list_apartments():
    check_in, check_out = request.args.get("from"), request.args.get("to")
    min_rooms = query_int("min_rooms", minimum=1) or 1
    if (check_in is None) != (check_out is None):
        raise ApiError(400, "validation_error", "Query parameters 'from' and 'to' must be given together")
    if check_in is not None:
        return jsonify(svc().search_available(check_in, check_out, min_rooms))
    return jsonify([a for a in svc().list_apartments() if a["rooms"] >= min_rooms])


@api.post("/apartments")
def create_apartment():
    body = json_body(APARTMENT_FIELDS, required=("name", "address"))
    apt = svc().add_apartment(body["name"], body["address"],
                              rooms=body.get("rooms", 1), price=body.get("price", 0.0))
    return created(apt, "api.get_apartment", apartment_id=apt["id"])


@api.get("/apartments/<int:apartment_id>")
def get_apartment(apartment_id: int):
    return jsonify(svc().get_apartment(apartment_id))


@api.patch("/apartments/<int:apartment_id>")
def update_apartment(apartment_id: int):
    body = json_body(APARTMENT_FIELDS)
    return jsonify(svc().update_apartment(apartment_id, **body))


@api.delete("/apartments/<int:apartment_id>")
def delete_apartment(apartment_id: int):
    svc().remove_apartment(apartment_id)
    return "", 204


# ---------- bookings ----------

BOOKING_FIELDS = {"apartment_id": int, "guest": str, "check_in": str, "check_out": str}


@api.get("/bookings")
def list_bookings():
    return jsonify(svc().list_bookings(
        apt_id=query_int("apartment_id"),
        guest=request.args.get("guest") or None,
        include_cancelled=query_bool("include_cancelled"),
    ))


@api.post("/bookings")
def create_booking():
    body = json_body(BOOKING_FIELDS, required=("apartment_id", "check_in", "check_out"))
    booking = svc().create_booking(body["apartment_id"], body.get("guest", ""),
                                   body["check_in"], body["check_out"])
    return created(booking, "api.get_booking", booking_id=booking["id"])


@api.get("/bookings/<int:booking_id>")
def get_booking(booking_id: int):
    return jsonify(svc().get_booking(booking_id))


@api.patch("/bookings/<int:booking_id>")
def update_booking(booking_id: int):
    body = json_body({**BOOKING_FIELDS, "status": str})
    if "status" in body:
        if body["status"] != CANCELLED:
            raise ApiError(400, "validation_error", "'status' can only be set to 'cancelled'")
        if len(body) > 1:
            raise ApiError(400, "validation_error", "Cancelling cannot be combined with other changes")
        return jsonify(svc().cancel_booking(booking_id))
    return jsonify(svc().change_booking(
        booking_id, apt_id=body.get("apartment_id"), guest=body.get("guest"),
        check_in=body.get("check_in"), check_out=body.get("check_out")))


# ---------- meta ----------

@api.get("/health")
def health():
    return jsonify(status="ok")


@api.get("/openapi.yaml")
def openapi_spec():
    return Response(SPEC_PATH.read_text(encoding="utf-8"), mimetype="application/yaml")

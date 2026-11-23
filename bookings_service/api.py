"""REST API of the booking service, mounted under /api: bookings, health and the spec.

/api/apartments belongs to the apartments service; the NGINX gateway routes
it there. The whole public API is documented in openapi.yaml, served here.
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

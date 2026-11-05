"""REST API: JSON resources for apartments and bookings, mounted under /api.

The API contract is documented in openapi.yaml; keep the two in sync.
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, url_for
from werkzeug.exceptions import HTTPException

from .service import CANCELLED, BookingError, ConflictError, NotFoundError

SPEC_PATH = Path(__file__).with_name("openapi.yaml")

api = Blueprint("api", __name__, url_prefix="/api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str):
    return jsonify(error={"code": code, "message": message}), status


@api.errorhandler(ApiError)
def _api_error(e: ApiError):
    return error_response(e.status, e.code, e.message)


@api.errorhandler(BookingError)
def _booking_error(e: BookingError):
    if isinstance(e, NotFoundError):
        return error_response(404, "not_found", str(e))
    if isinstance(e, ConflictError):
        return error_response(409, "conflict", str(e))
    return error_response(400, "validation_error", str(e))


def handle_http_error(e: HTTPException):
    """Return JSON instead of HTML for HTTP errors (404, 405, ...) under /api."""
    if not request.path.startswith(api.url_prefix):
        return e
    code = (e.name or "error").lower().replace(" ", "_")
    return error_response(e.code or 500, code, e.description or e.name)


def svc():
    return current_app.extensions["booking_service"]


# ---------- request parsing ----------

def _type_name(kind) -> str:
    return {str: "a string", int: "an integer", float: "a number"}[kind]


def _check_type(field: str, value, kind):
    ok = isinstance(value, (int, float) if kind is float else kind) and not isinstance(value, bool)
    if not ok:
        raise ApiError(400, "validation_error", f"'{field}' must be {_type_name(kind)}")
    return value


def json_body(fields: dict, required=()) -> dict:
    """Parse a JSON object body, rejecting unknown fields, missing fields and wrong types."""
    if not request.is_json:
        raise ApiError(415, "unsupported_media_type", "Request body must be JSON (Content-Type: application/json)")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "validation_error", "Request body must be a JSON object")
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ApiError(400, "validation_error", f"Unknown field(s): {', '.join(unknown)}")
    missing = [f for f in required if f not in data]
    if missing:
        raise ApiError(400, "validation_error", f"Missing required field(s): {', '.join(missing)}")
    return {f: _check_type(f, v, fields[f]) for f, v in data.items()}


def query_int(name: str, minimum: int | None = None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, "validation_error", f"Query parameter '{name}' must be an integer") from None
    if minimum is not None and value < minimum:
        raise ApiError(400, "validation_error", f"Query parameter '{name}' must be at least {minimum}")
    return value


def query_bool(name: str) -> bool:
    raw = request.args.get(name, "false").lower()
    if raw not in ("true", "false"):
        raise ApiError(400, "validation_error", f"Query parameter '{name}' must be 'true' or 'false'")
    return raw == "true"


def created(resource: dict, endpoint: str, **ids):
    response = jsonify(resource)
    response.status_code = 201
    response.headers["Location"] = url_for(endpoint, **ids)
    return response


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

"""JSON API helpers shared by the services: error responses and request parsing.

Every service answers errors in the same shape:
    {"error": {"code": "...", "message": "..."}}
"""
from __future__ import annotations

from flask import jsonify, request, url_for
from werkzeug.exceptions import HTTPException

from .errors import BookingError, ConflictError, NotFoundError, ServiceUnavailableError

API_PREFIX = "/api"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str):
    return jsonify(error={"code": code, "message": message}), status


def _api_error(e: ApiError):
    return error_response(e.status, e.code, e.message)


def _booking_error(e: BookingError):
    if isinstance(e, NotFoundError):
        return error_response(404, "not_found", str(e))
    if isinstance(e, ConflictError):
        return error_response(409, "conflict", str(e))
    if isinstance(e, ServiceUnavailableError):
        return error_response(503, "service_unavailable", str(e))
    return error_response(400, "validation_error", str(e))


def register_error_handlers(blueprint) -> None:
    """Turn ApiError and the service errors into JSON responses."""
    blueprint.register_error_handler(ApiError, _api_error)
    blueprint.register_error_handler(BookingError, _booking_error)


def handle_http_error(e: HTTPException):
    """Return JSON instead of HTML for HTTP errors (404, 405, ...) under /api."""
    if not request.path.startswith(API_PREFIX):
        return e
    code = (e.name or "error").lower().replace(" ", "_")
    return error_response(e.code or 500, code, e.description or e.name)


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

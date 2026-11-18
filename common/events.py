"""Domain events that services publish to RabbitMQ.

Every event is a JSON envelope:
    {"event_id": "<uuid4>", "type": "apartment.updated",
     "occurred_at": "2026-11-18T10:00:00+00:00", "data": {...}}

It is published to the topic exchange EXCHANGE with the type as routing key.
Delivery is at least once, so consumers must skip event_ids they have already
processed, and must not let an older version overwrite a newer one.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

EXCHANGE = "apartments"

APARTMENT_CREATED = "apartment.created"  # data: apartment + version
APARTMENT_UPDATED = "apartment.updated"  # data: apartment + version
APARTMENT_DELETED = "apartment.deleted"  # data: {id, version}


def new_event(event_type: str, data: dict) -> dict:
    return {"event_id": str(uuid.uuid4()), "type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(), "data": data}


def encode(event: dict) -> bytes:
    return json.dumps(event).encode()


def decode(body: bytes) -> dict:
    """Parse and check an envelope; raises ValueError if it is malformed."""
    event = json.loads(body)
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise ValueError("event must be an object with a 'data' object")
    for key in ("event_id", "type"):
        if not isinstance(event.get(key), str):
            raise ValueError(f"event has no '{key}'")
    for key in ("id", "version"):
        value = event["data"].get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"event data has no integer '{key}'")
    return event

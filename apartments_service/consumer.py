"""Keeps the apartments service's bookings replica up to date from booking events.

Each event is applied in one transaction together with recording its
event_id, so a redelivered event changes nothing, and only if its version is
newer than what the replica has, so events arriving out of order can't roll a
booking back. Cancelled bookings stay in the replica with status "cancelled".
"""
from __future__ import annotations

import logging

from common.events import BOOKING_CANCELLED, BOOKING_CHANGED, BOOKING_CREATED, decode

from .repo import ApartmentRepo

QUEUE = "apartments.bookings"
BINDING = "booking.*"
BOOKING_EVENTS = (BOOKING_CREATED, BOOKING_CHANGED, BOOKING_CANCELLED)
FIELDS = ("id", "apartment_id", "check_in", "check_out", "status", "version")

log = logging.getLogger("apartments_service.consumer")


def handle_booking_event(repo: ApartmentRepo, event: dict) -> bool:
    """Apply one booking event to the replica; returns False if it changed nothing."""
    data = event["data"]
    with repo.db.transaction(immediate=True) as conn:
        if conn.execute("SELECT 1 FROM processed_events WHERE event_id = ?",
                        (event["event_id"],)).fetchone():
            return False
        current = repo.bookings.get(conn, data["id"])
        applied = event["type"] in BOOKING_EVENTS and (current is None or data["version"] > current["version"])
        if applied:
            repo.bookings.put(conn, {field: data[field] for field in FIELDS})
        conn.execute("INSERT INTO processed_events (event_id) VALUES (?)", (event["event_id"],))
        return applied


def on_message(repo: ApartmentRepo, body: bytes) -> None:
    try:
        event = decode(body)
        if event["type"] in BOOKING_EVENTS:
            missing = [f for f in FIELDS if f not in event["data"]]
            if missing:
                raise ValueError(f"booking event data has no {', '.join(missing)}")
    except ValueError as e:
        # Redelivering would fail the same way forever: log it and drop it.
        log.warning("dropping malformed event: %s", e)
        return
    if handle_booking_event(repo, event):
        log.info("applied %s for booking %s (version %s)",
                 event["type"], event["data"]["id"], event["data"]["version"])

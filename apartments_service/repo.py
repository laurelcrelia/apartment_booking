"""SQLite repository for apartments. Rows are returned as plain dicts in the API's shape.

Every change also writes an event to the outbox in the same transaction (see
common/outbox.py); the worker publishes it to RabbitMQ afterwards. The same
database keeps a replica of the bookings, fed by the booking service's events
(see consumer.py), for rules that need to know about bookings.
"""
from __future__ import annotations

from pathlib import Path

from common.db import Database
from common.events import APARTMENT_CREATED, APARTMENT_DELETED, APARTMENT_UPDATED
from common.outbox import OUTBOX_SCHEMA, Outbox, enqueue, mark_snapshot_done

APARTMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS apartments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- AUTOINCREMENT: IDs are never reused
    name    TEXT    NOT NULL,
    address TEXT    NOT NULL DEFAULT '',
    rooms   INTEGER NOT NULL,
    price   REAL    NOT NULL,
    version INTEGER NOT NULL DEFAULT 1          -- bumped on every change
);

-- Read-only copy of the bookings, fed by the booking service's events.
CREATE TABLE IF NOT EXISTS bookings_replica (
    id           INTEGER PRIMARY KEY,
    apartment_id INTEGER NOT NULL,
    check_in     TEXT    NOT NULL,
    check_out    TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    version      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS bookings_replica_by_apartment ON bookings_replica (apartment_id, status);
-- Events already applied, so a redelivered event is applied only once.
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY
);
""" + OUTBOX_SCHEMA

APARTMENT_COLUMNS = "id, name, address, rooms, price"
REPLICA_COLUMNS = "id, apartment_id, check_in, check_out, status, version"


def _dict(row) -> dict | None:
    return None if row is None else dict(row)


def enqueue_snapshot(conn) -> int:
    """Queue an apartment.created event for every apartment as it is now.

    For apartments that existed before events did (or were imported). Safe to
    repeat: consumers ignore versions they already have.
    """
    rows = conn.execute(f"SELECT {APARTMENT_COLUMNS}, version FROM apartments ORDER BY id").fetchall()
    for row in rows:
        enqueue(conn, APARTMENT_CREATED, dict(row))
    mark_snapshot_done(conn)
    return len(rows)


class BookingsReplica:
    """The apartments service's copy of the bookings; see consumer.py."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, conn, booking_id: int) -> dict | None:
        return _dict(conn.execute(f"SELECT {REPLICA_COLUMNS} FROM bookings_replica WHERE id = ?",
                                  (booking_id,)).fetchone())

    def put(self, conn, booking: dict) -> None:
        conn.execute(
            "INSERT INTO bookings_replica (id, apartment_id, check_in, check_out, status, version)"
            " VALUES (:id, :apartment_id, :check_in, :check_out, :status, :version)"
            " ON CONFLICT (id) DO UPDATE SET apartment_id = excluded.apartment_id,"
            " check_in = excluded.check_in, check_out = excluded.check_out,"
            " status = excluded.status, version = excluded.version", booking)

    def list(self) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(r) for r in conn.execute(f"SELECT {REPLICA_COLUMNS} FROM bookings_replica ORDER BY id")]


class ApartmentRepo:
    def __init__(self, path: str | Path):
        self.db = Database(path, APARTMENTS_SCHEMA)
        self.outbox = Outbox(self.db, enqueue_snapshot, table="apartments")
        self.bookings = BookingsReplica(self.db)

    # Every transaction that writes is immediate: the worker writes to the same
    # database from another process, see Database.transaction.

    def add(self, name: str, address: str, rooms: int, price: float) -> dict:
        with self.db.transaction(immediate=True) as conn:
            cur = conn.execute("INSERT INTO apartments (name, address, rooms, price) VALUES (?, ?, ?, ?)",
                               (name, address, rooms, price))
            apt, version = self._get_versioned(conn, cur.lastrowid)
            enqueue(conn, APARTMENT_CREATED, {**apt, "version": version})
            return apt

    def get(self, apt_id: int) -> dict | None:
        with self.db.transaction() as conn:
            return self._get(conn, apt_id)

    def list(self) -> list[dict]:
        with self.db.transaction() as conn:
            rows = conn.execute(f"SELECT {APARTMENT_COLUMNS} FROM apartments ORDER BY id")
            return [dict(r) for r in rows]

    def update(self, apt_id: int, **fields) -> dict | None:
        """Change the given columns; returns the updated row, or None if it doesn't exist."""
        if not fields:
            return self.get(apt_id)
        with self.db.transaction(immediate=True) as conn:
            assignments = ", ".join(f"{column} = ?" for column in fields)
            conn.execute(f"UPDATE apartments SET {assignments}, version = version + 1 WHERE id = ?",
                         (*fields.values(), apt_id))
            apt, version = self._get_versioned(conn, apt_id)
            if apt is not None:
                enqueue(conn, APARTMENT_UPDATED, {**apt, "version": version})
            return apt

    def delete(self, apt_id: int) -> bool:
        with self.db.transaction(immediate=True) as conn:
            apt, version = self._get_versioned(conn, apt_id)
            if apt is None:
                return False
            conn.execute("DELETE FROM apartments WHERE id = ?", (apt_id,))
            # The deletion is one more change, so it gets the next version.
            enqueue(conn, APARTMENT_DELETED, {"id": apt_id, "version": version + 1})
            return True

    @staticmethod
    def _get(conn, apt_id: int) -> dict | None:
        return _dict(conn.execute(f"SELECT {APARTMENT_COLUMNS} FROM apartments WHERE id = ?",
                                  (apt_id,)).fetchone())

    @staticmethod
    def _get_versioned(conn, apt_id: int) -> tuple[dict | None, int | None]:
        row = conn.execute(f"SELECT {APARTMENT_COLUMNS}, version FROM apartments WHERE id = ?",
                           (apt_id,)).fetchone()
        if row is None:
            return None, None
        apt = dict(row)
        return apt, apt.pop("version")

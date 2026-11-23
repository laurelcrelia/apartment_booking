"""SQLite repository for bookings. Rows are returned as plain dicts in the API's shape.

Bookings refer to apartments by ID only. Apartments belong to the apartments
service and live in its own database, so there is no foreign key. This
database keeps a replica of the apartment fields that booking rules need,
kept up to date from the apartments service's events (see consumer.py).

Every booking change also writes an event to the outbox in the same
transaction (see common/outbox.py); the worker publishes it to RabbitMQ, so
the apartments service learns about bookings.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from common.db import Database
from common.events import BOOKING_CANCELLED, BOOKING_CHANGED, BOOKING_CREATED
from common.outbox import OUTBOX_SCHEMA, Outbox, enqueue, mark_snapshot_done

BOOKINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    apartment_id INTEGER NOT NULL,
    guest        TEXT    NOT NULL DEFAULT '',
    check_in     TEXT    NOT NULL,  -- YYYY-MM-DD, so text order is date order
    check_out    TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'active',
    version      INTEGER NOT NULL DEFAULT 1  -- bumped on every change
);
CREATE INDEX IF NOT EXISTS bookings_by_apartment ON bookings (apartment_id, status);

-- Read-only copy of apartments, fed by events. A deleted apartment stays as a
-- tombstone (deleted = 1) so a late, older event can't bring it back.
CREATE TABLE IF NOT EXISTS apartments_replica (
    id      INTEGER PRIMARY KEY,
    name    TEXT    NOT NULL,
    address TEXT    NOT NULL,
    rooms   INTEGER NOT NULL,
    price   REAL    NOT NULL,
    version INTEGER NOT NULL,  -- version of the apartment this row reflects; 0 = fetched over HTTP
    deleted INTEGER NOT NULL DEFAULT 0
);
-- Events already applied, so a redelivered event is applied only once.
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY
);
""" + OUTBOX_SCHEMA

BOOKING_COLUMNS = "id, apartment_id, guest, check_in, check_out, status"
EVENT_COLUMNS = "id, apartment_id, check_in, check_out, status, version"  # no guest name
APARTMENT_COLUMNS = "id, name, address, rooms, price"


def _dict(row) -> dict | None:
    return None if row is None else dict(row)


class BookingTable:
    """Booking queries on one open connection, so several of them can share a transaction."""

    def __init__(self, conn):
        self.conn = conn

    def get(self, booking_id: int) -> dict | None:
        return _dict(self.conn.execute(f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE id = ?",
                                       (booking_id,)).fetchone())

    def list(self, apt_id: int | None = None, include_cancelled: bool = False) -> list[dict]:
        where, params = [], []
        if apt_id is not None:
            where.append("apartment_id = ?")
            params.append(apt_id)
        if not include_cancelled:
            where.append("status = 'active'")
        sql = f"SELECT {BOOKING_COLUMNS} FROM bookings"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY check_in, id", params)]

    def first_overlap(self, apt_id: int, check_in: str, check_out: str,
                      ignore_id: int | None = None) -> dict | None:
        """The first active booking of the apartment that overlaps [check_in, check_out)."""
        return _dict(self.conn.execute(
            f"SELECT {BOOKING_COLUMNS} FROM bookings"
            " WHERE apartment_id = ? AND status = 'active' AND id IS NOT ?"
            " AND check_in < ? AND ? < check_out ORDER BY id LIMIT 1",
            (apt_id, ignore_id, check_out, check_in)).fetchone())

    def available_apartments(self, check_in: str, check_out: str, min_rooms: int) -> list[dict]:
        """Replica apartments with no active booking overlapping [check_in, check_out)."""
        rows = self.conn.execute(
            f"SELECT {APARTMENT_COLUMNS} FROM apartments_replica"
            " WHERE deleted = 0 AND rooms >= ? AND id NOT IN ("
            "   SELECT apartment_id FROM bookings"
            "   WHERE status = 'active' AND check_in < ? AND ? < check_out)"
            " ORDER BY id", (min_rooms, check_out, check_in))
        return [dict(r) for r in rows]

    def insert(self, apt_id: int, guest: str, check_in: str, check_out: str, status: str) -> dict:
        cur = self.conn.execute(
            "INSERT INTO bookings (apartment_id, guest, check_in, check_out, status) VALUES (?, ?, ?, ?, ?)",
            (apt_id, guest, check_in, check_out, status))
        self._announce(BOOKING_CREATED, cur.lastrowid)
        return self.get(cur.lastrowid)

    def update(self, booking_id: int, **fields) -> dict:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        self.conn.execute(f"UPDATE bookings SET {assignments}, version = version + 1 WHERE id = ?",
                          (*fields.values(), booking_id))
        self._announce(BOOKING_CANCELLED if fields.get("status") == "cancelled" else BOOKING_CHANGED,
                       booking_id)
        return self.get(booking_id)

    def _announce(self, event_type: str, booking_id: int) -> None:
        """Queue the event for a booking change, in the same transaction as the change."""
        row = self.conn.execute(f"SELECT {EVENT_COLUMNS} FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        enqueue(self.conn, event_type, dict(row))


    # ---------- apartments replica ----------

    def replica_get(self, apt_id: int) -> dict | None:
        """The replica row including version and deleted flag, or None if unknown."""
        return _dict(self.conn.execute(f"SELECT {APARTMENT_COLUMNS}, version, deleted"
                                       " FROM apartments_replica WHERE id = ?", (apt_id,)).fetchone())

    def replica_put(self, apt: dict, version: int, only_if_missing: bool = False) -> None:
        values = (apt["id"], apt["name"], apt["address"], apt["rooms"], apt["price"], version)
        if only_if_missing:
            self.conn.execute("INSERT OR IGNORE INTO apartments_replica"
                              " (id, name, address, rooms, price, version) VALUES (?, ?, ?, ?, ?, ?)", values)
        else:
            self.conn.execute(
                "INSERT INTO apartments_replica (id, name, address, rooms, price, version)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET name = excluded.name,"
                " address = excluded.address, rooms = excluded.rooms, price = excluded.price,"
                " version = excluded.version, deleted = 0", values)

    def replica_delete(self, apt_id: int, version: int) -> None:
        self.conn.execute(
            "INSERT INTO apartments_replica (id, name, address, rooms, price, version, deleted)"
            " VALUES (?, '', '', 0, 0, ?, 1)"
            " ON CONFLICT (id) DO UPDATE SET version = excluded.version, deleted = 1", (apt_id, version))

    def event_processed(self, event_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM processed_events WHERE event_id = ?",
                                 (event_id,)).fetchone() is not None

    def record_event(self, event_id: str) -> None:
        self.conn.execute("INSERT INTO processed_events (event_id) VALUES (?)", (event_id,))


def enqueue_snapshot(conn) -> int:
    """Queue a booking.created event for every booking as it is now.

    For bookings that existed before events did (or were imported). Safe to
    repeat: consumers ignore versions they already have.
    """
    rows = conn.execute(f"SELECT {EVENT_COLUMNS} FROM bookings ORDER BY id").fetchall()
    for row in rows:
        enqueue(conn, BOOKING_CREATED, dict(row))
    mark_snapshot_done(conn)
    return len(rows)


def _add_version_column(db: Database) -> None:
    """Databases from before booking events have no version column; add it."""
    with db.transaction(immediate=True) as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(bookings)")}
        if "version" not in columns:
            conn.execute("ALTER TABLE bookings ADD COLUMN version INTEGER NOT NULL DEFAULT 1")


class BookingRepo:
    def __init__(self, path: str | Path):
        self.db = Database(path, BOOKINGS_SCHEMA)
        _add_version_column(self.db)
        self.outbox = Outbox(self.db, enqueue_snapshot, table="bookings")

    @contextmanager
    def reading(self):
        with self.db.transaction() as conn:
            yield BookingTable(conn)

    @contextmanager
    def writing(self):
        """A transaction holding the write lock: checks inside it stay true until it commits."""
        with self.db.transaction(immediate=True) as conn:
            yield BookingTable(conn)

"""SQLite repository for bookings. Rows are returned as plain dicts in the API's shape.

Bookings refer to apartments by ID only. Apartments belong to the apartments
service and live in its own database, so there is no foreign key.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from common.db import Database

BOOKINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    apartment_id INTEGER NOT NULL,
    guest        TEXT    NOT NULL DEFAULT '',
    check_in     TEXT    NOT NULL,  -- YYYY-MM-DD, so text order is date order
    check_out    TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS bookings_by_apartment ON bookings (apartment_id, status);
"""

BOOKING_COLUMNS = "id, apartment_id, guest, check_in, check_out, status"


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

    def busy_apartments(self, check_in: str, check_out: str) -> set[int]:
        rows = self.conn.execute(
            "SELECT DISTINCT apartment_id FROM bookings"
            " WHERE status = 'active' AND check_in < ? AND ? < check_out", (check_out, check_in))
        return {r[0] for r in rows}

    def insert(self, apt_id: int, guest: str, check_in: str, check_out: str, status: str) -> dict:
        cur = self.conn.execute(
            "INSERT INTO bookings (apartment_id, guest, check_in, check_out, status) VALUES (?, ?, ?, ?, ?)",
            (apt_id, guest, check_in, check_out, status))
        return self.get(cur.lastrowid)

    def update(self, booking_id: int, **fields) -> dict:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        self.conn.execute(f"UPDATE bookings SET {assignments} WHERE id = ?", (*fields.values(), booking_id))
        return self.get(booking_id)


class BookingRepo:
    def __init__(self, path: str | Path):
        self.db = Database(path, BOOKINGS_SCHEMA)

    @contextmanager
    def reading(self):
        with self.db.transaction() as conn:
            yield BookingTable(conn)

    @contextmanager
    def writing(self):
        """A transaction holding the write lock: checks inside it stay true until it commits."""
        with self.db.transaction(immediate=True) as conn:
            yield BookingTable(conn)

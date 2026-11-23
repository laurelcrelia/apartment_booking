"""SQLite repository for apartments. Rows are returned as plain dicts in the API's shape.

Every change also writes an event to the outbox table in the same transaction,
so a change and its event are saved together or not at all. The relay
(relay.py) publishes outbox events to RabbitMQ afterwards.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from common.db import Database
from common.events import APARTMENT_CREATED, APARTMENT_DELETED, APARTMENT_UPDATED, new_event

APARTMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS apartments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- AUTOINCREMENT: IDs are never reused
    name    TEXT    NOT NULL,
    address TEXT    NOT NULL DEFAULT '',
    rooms   INTEGER NOT NULL,
    price   REAL    NOT NULL,
    version INTEGER NOT NULL DEFAULT 1          -- bumped on every change
);
CREATE TABLE IF NOT EXISTS outbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,
    payload      TEXT NOT NULL,                 -- the whole event as JSON
    created_at   TEXT NOT NULL,
    published_at TEXT                           -- NULL until the relay has published it
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox (id) WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS outbox_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

APARTMENT_COLUMNS = "id, name, address, rooms, price"


def _dict(row) -> dict | None:
    return None if row is None else dict(row)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue(conn, event_type: str, data: dict) -> None:
    """Add an event to the outbox, inside the caller's transaction."""
    event = new_event(event_type, data)
    conn.execute("INSERT INTO outbox (event_id, payload, created_at) VALUES (?, ?, ?)",
                 (event["event_id"], json.dumps(event), _now()))


def enqueue_snapshot(conn) -> int:
    """Queue an apartment.created event for every apartment as it is now.

    For apartments that existed before events did (or were imported). Safe to
    repeat: consumers ignore versions they already have.
    """
    rows = conn.execute(f"SELECT {APARTMENT_COLUMNS}, version FROM apartments ORDER BY id").fetchall()
    for row in rows:
        enqueue(conn, APARTMENT_CREATED, dict(row))
    conn.execute("INSERT OR REPLACE INTO outbox_state (key, value) VALUES ('snapshot', ?)", (_now(),))
    return len(rows)


class Outbox:
    def __init__(self, db: Database):
        self.db = db

    def pending(self, limit: int = 100) -> list[tuple[int, dict]]:
        """Unpublished events, oldest first, as (outbox row id, event)."""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id, payload FROM outbox WHERE published_at IS NULL"
                                " ORDER BY id LIMIT ?", (limit,))
            return [(r["id"], json.loads(r["payload"])) for r in rows]

    def mark_published(self, row_id: int) -> None:
        with self.db.transaction(immediate=True) as conn:
            conn.execute("UPDATE outbox SET published_at = ? WHERE id = ?", (_now(), row_id))

    def snapshot_once(self) -> int:
        """Queue a snapshot of all apartments if this database had apartments before
        it had an outbox (an upgraded database) and hasn't had one yet."""
        with self.db.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM outbox_state WHERE key = 'snapshot'").fetchone():
                return 0
            return enqueue_snapshot(conn)


class ApartmentRepo:
    def __init__(self, path: str | Path):
        self.db = Database(path, APARTMENTS_SCHEMA)
        self.outbox = Outbox(self.db)
        with self.db.transaction(immediate=True) as conn:
            # A database without apartments has nothing from before events existed.
            if conn.execute("SELECT 1 FROM apartments LIMIT 1").fetchone() is None:
                conn.execute("INSERT OR IGNORE INTO outbox_state (key, value)"
                             " VALUES ('snapshot', 'not needed: no apartments yet')")

    # Every transaction that writes is immediate: the relay writes to the same
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

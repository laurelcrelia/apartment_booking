"""Transactional outbox: events saved in the same transaction as the change.

A service writes its data change and the matching event in one SQLite
transaction (enqueue), so it can never have one without the other. A relay
(relay.py) publishes the saved events afterwards.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .db import Database
from .events import new_event

OUTBOX_SCHEMA = """
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


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue(conn, event_type: str, data: dict) -> None:
    """Add an event to the outbox, inside the caller's transaction."""
    event = new_event(event_type, data)
    conn.execute("INSERT INTO outbox (event_id, payload, created_at) VALUES (?, ?, ?)",
                 (event["event_id"], json.dumps(event), now()))


def mark_snapshot_done(conn) -> None:
    conn.execute("INSERT OR REPLACE INTO outbox_state (key, value) VALUES ('snapshot', ?)", (now(),))


class Outbox:
    """The outbox of one database.

    snapshot(conn) queues an event for every existing row; snapshot_once()
    runs it for databases that had data before they had an outbox.
    """

    def __init__(self, db: Database, snapshot, table: str):
        self.db = db
        self.snapshot = snapshot
        with db.transaction(immediate=True) as conn:
            # A table without rows has nothing from before events existed.
            if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is None:
                conn.execute("INSERT OR IGNORE INTO outbox_state (key, value)"
                             " VALUES ('snapshot', 'not needed: no rows yet')")

    def pending(self, limit: int = 100) -> list[tuple[int, dict]]:
        """Unpublished events, oldest first, as (outbox row id, event)."""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id, payload FROM outbox WHERE published_at IS NULL"
                                " ORDER BY id LIMIT ?", (limit,))
            return [(r["id"], json.loads(r["payload"])) for r in rows]

    def mark_published(self, row_id: int) -> None:
        with self.db.transaction(immediate=True) as conn:
            conn.execute("UPDATE outbox SET published_at = ? WHERE id = ?", (now(), row_id))

    def snapshot_once(self) -> int:
        """Queue a snapshot of all rows if this database had rows before it had
        an outbox (an upgraded database) and hasn't had one yet."""
        with self.db.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM outbox_state WHERE key = 'snapshot'").fetchone():
                return 0
            count = self.snapshot(conn)
            mark_snapshot_done(conn)
            return count

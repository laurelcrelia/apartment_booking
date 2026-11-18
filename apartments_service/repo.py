"""SQLite repository for apartments. Rows are returned as plain dicts in the API's shape."""
from __future__ import annotations

from pathlib import Path

from common.db import Database

APARTMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS apartments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- AUTOINCREMENT: IDs are never reused
    name    TEXT    NOT NULL,
    address TEXT    NOT NULL DEFAULT '',
    rooms   INTEGER NOT NULL,
    price   REAL    NOT NULL,
    version INTEGER NOT NULL DEFAULT 1          -- bumped on every change
);
"""

APARTMENT_COLUMNS = "id, name, address, rooms, price"


def _dict(row) -> dict | None:
    return None if row is None else dict(row)


class ApartmentRepo:
    def __init__(self, path: str | Path):
        self.db = Database(path, APARTMENTS_SCHEMA)

    def add(self, name: str, address: str, rooms: int, price: float) -> dict:
        with self.db.transaction() as conn:
            cur = conn.execute("INSERT INTO apartments (name, address, rooms, price) VALUES (?, ?, ?, ?)",
                               (name, address, rooms, price))
            return self._get(conn, cur.lastrowid)

    def get(self, apt_id: int) -> dict | None:
        with self.db.transaction() as conn:
            return self._get(conn, apt_id)

    def list(self) -> list[dict]:
        with self.db.transaction() as conn:
            rows = conn.execute(f"SELECT {APARTMENT_COLUMNS} FROM apartments ORDER BY id")
            return [dict(r) for r in rows]

    def update(self, apt_id: int, **fields) -> dict | None:
        """Change the given columns; returns the updated row, or None if it doesn't exist."""
        with self.db.transaction() as conn:
            if fields:
                assignments = ", ".join(f"{column} = ?" for column in fields)
                conn.execute(f"UPDATE apartments SET {assignments}, version = version + 1 WHERE id = ?",
                             (*fields.values(), apt_id))
            return self._get(conn, apt_id)

    def delete(self, apt_id: int) -> bool:
        with self.db.transaction() as conn:
            return conn.execute("DELETE FROM apartments WHERE id = ?", (apt_id,)).rowcount == 1

    @staticmethod
    def _get(conn, apt_id: int) -> dict | None:
        return _dict(conn.execute(f"SELECT {APARTMENT_COLUMNS} FROM apartments WHERE id = ?",
                                  (apt_id,)).fetchone())

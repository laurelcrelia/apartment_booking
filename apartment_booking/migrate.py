"""Copy data from the old JSON data file into the SQLite databases.

    python -m apartment_booking.migrate data.json [--apartments-db PATH] [--bookings-db PATH]

IDs are kept, so bookings still point at the right apartments, and new IDs
continue where the JSON file left off. Refuses to write into databases that
already contain data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from apartments_service.repo import ApartmentRepo, enqueue_snapshot

from .repos import BookingRepo


class MigrationError(Exception):
    pass


def _set_next_id(conn, table: str, next_id: int) -> None:
    # sqlite_sequence holds the last ID handed out by AUTOINCREMENT.
    if conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (next_id - 1, table)).rowcount == 0:
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, next_id - 1))


def migrate(json_path: str, apartments_db: str, bookings_db: str) -> tuple[int, int]:
    """Returns (number of apartments, number of bookings) copied."""
    with open(json_path, encoding="utf-8") as f:
        state = json.load(f)
    apartments, bookings = ApartmentRepo(apartments_db), BookingRepo(bookings_db)
    if apartments.list():
        raise MigrationError(f"{apartments_db} already contains apartments")
    with bookings.reading() as table:
        if table.list(include_cancelled=True):
            raise MigrationError(f"{bookings_db} already contains bookings")

    apts = sorted(state["apartments"].values(), key=lambda a: a["id"])
    with apartments.db.transaction(immediate=True) as conn:
        conn.executemany(
            "INSERT INTO apartments (id, name, address, rooms, price) VALUES (?, ?, ?, ?, ?)",
            [(a["id"], a["name"], a["address"], a["rooms"], a["price"]) for a in apts])
        _set_next_id(conn, "apartments", state["next_apartment_id"])
        # Announce the imported apartments, so the booking side's replica learns about them.
        enqueue_snapshot(conn)

    books = sorted(state["bookings"].values(), key=lambda b: b["id"])
    with bookings.db.transaction(immediate=True) as conn:
        conn.executemany(
            "INSERT INTO bookings (id, apartment_id, guest, check_in, check_out, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(b["id"], b["apartment_id"], b["guest"], b["check_in"], b["check_out"], b["status"])
             for b in books])
        _set_next_id(conn, "bookings", state["next_booking_id"])
    return len(apts), len(books)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m apartment_booking.migrate",
                                description="Copy a JSON data file into the SQLite databases.")
    p.add_argument("json_file")
    p.add_argument("--apartments-db", default=os.environ.get("APARTMENTS_DB", "apartments.db"))
    p.add_argument("--bookings-db", default=os.environ.get("BOOKINGS_DB", "bookings.db"))
    args = p.parse_args(argv)
    try:
        n_apts, n_books = migrate(args.json_file, args.apartments_db, args.bookings_db)
    except (OSError, ValueError, KeyError, MigrationError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Migrated {n_apts} apartments to {args.apartments_db} "
          f"and {n_books} bookings to {args.bookings_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO

from apartment_booking.migrate import MigrationError, main, migrate
from apartment_booking.repos import BookingRepo
from apartments_service.repo import ApartmentRepo
from apartment_booking.service import OverlapError, open_service


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.apartments_db = os.path.join(self.dir, "apartments.db")
        self.bookings_db = os.path.join(self.dir, "bookings.db")


class ApartmentRepoTests(TempDirTestCase):
    def test_round_trip_and_shape(self):
        repo = ApartmentRepo(self.apartments_db)
        a = repo.add("Loft", "1 Main St", 2, 80)
        self.assertEqual(a, {"id": 1, "name": "Loft", "address": "1 Main St", "rooms": 2, "price": 80.0})
        self.assertEqual(ApartmentRepo(self.apartments_db).get(1), a)
        self.assertIsNone(repo.get(2))

    def test_update_bumps_version_only_when_something_changes(self):
        repo = ApartmentRepo(self.apartments_db)
        repo.add("Loft", "x", 1, 0)
        def version():
            with closing(repo.db._connect()) as conn:
                return conn.execute("SELECT version FROM apartments").fetchone()[0]
        self.assertEqual(repo.update(1)["name"], "Loft")
        self.assertEqual(version(), 1)
        self.assertEqual(repo.update(1, name="Big Loft", rooms=3)["rooms"], 3)
        self.assertEqual(version(), 2)
        self.assertIsNone(repo.update(9, name="x"))

    def test_ids_not_reused_after_restart(self):
        repo = ApartmentRepo(self.apartments_db)
        repo.add("A", "x", 1, 0)
        repo.add("B", "x", 1, 0)
        self.assertTrue(repo.delete(2))
        self.assertFalse(repo.delete(2))
        self.assertEqual(ApartmentRepo(self.apartments_db).add("C", "x", 1, 0)["id"], 3)

    def test_creates_parent_directories(self):
        path = os.path.join(self.dir, "nested", "dir", "apartments.db")
        ApartmentRepo(path).add("A", "x", 1, 0)
        self.assertTrue(os.path.exists(path))


class TransactionTests(TempDirTestCase):
    def test_apartment_writes_survive_another_process_writing_meanwhile(self):
        # Regression: delete used to read, then write, without the write lock.
        # When the relay (another process) committed in between, SQLite failed
        # the delete at once with "database is locked".
        repo = ApartmentRepo(self.apartments_db)
        repo.add("Loft", "x", 1, 0)
        relay = sqlite3.connect(self.apartments_db, timeout=0.05, isolation_level=None)
        self.addCleanup(relay.close)
        read_versioned = repo._get_versioned
        relay_results = []

        def read_then_let_the_relay_write(conn, apt_id):
            result = read_versioned(conn, apt_id)
            try:
                relay.execute("UPDATE outbox SET published_at = 'now'")
                relay_results.append("wrote")
            except sqlite3.OperationalError:
                relay_results.append("blocked")
            return result

        repo._get_versioned = read_then_let_the_relay_write
        self.assertEqual(repo.update(1, price=10)["price"], 10)
        self.assertTrue(repo.delete(1))
        repo.add("Studio", "x", 1, 0)
        # The relay had to wait every time, because each write held the lock.
        self.assertEqual(relay_results, ["blocked"] * 3)

    def test_writing_holds_the_write_lock(self):
        repo = BookingRepo(self.bookings_db)
        other = sqlite3.connect(self.bookings_db, timeout=0.05, isolation_level=None)
        self.addCleanup(other.close)
        with repo.writing():
            with self.assertRaises(sqlite3.OperationalError):
                other.execute("BEGIN IMMEDIATE")
        other.execute("BEGIN IMMEDIATE")
        other.execute("ROLLBACK")

    def test_error_rolls_back(self):
        repo = BookingRepo(self.bookings_db)
        with self.assertRaises(RuntimeError):
            with repo.writing() as table:
                table.insert(1, "Ann", "2026-11-01", "2026-11-05", "active")
                raise RuntimeError("boom")
        with repo.reading() as table:
            self.assertEqual(table.list(include_cancelled=True), [])

    def test_concurrent_services_cannot_double_book(self):
        # Two services on the same files behave like two server processes.
        open_service(self.apartments_db, self.bookings_db).add_apartment("Loft", "x")
        services = [open_service(self.apartments_db, self.bookings_db) for _ in range(8)]
        barrier = threading.Barrier(len(services))
        results = []

        def book(svc):
            barrier.wait()
            try:
                svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
                results.append("ok")
            except OverlapError:
                results.append("overlap")

        threads = [threading.Thread(target=book, args=(s,)) for s in services]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["ok"] + ["overlap"] * 7)

    def test_memory_databases_are_independent(self):
        a, b = open_service(), open_service()
        a.add_apartment("Loft", "x")
        self.assertEqual(b.list_apartments(), [])


class MigrationTests(TempDirTestCase):
    STATE = {
        "next_apartment_id": 4,
        "next_booking_id": 3,
        "apartments": {
            "2": {"id": 2, "name": "Loft", "address": "1 Beach Rd", "rooms": 1, "price": 0.0},
            "3": {"id": 3, "name": "Studio", "address": "", "rooms": 2, "price": 75.5},
        },
        "bookings": {
            "1": {"id": 1, "apartment_id": 3, "guest": "Ann", "check_in": "2026-11-01",
                  "check_out": "2026-11-05", "status": "cancelled"},
            "2": {"id": 2, "apartment_id": 3, "guest": "Bob", "check_in": "2026-11-01",
                  "check_out": "2026-11-05", "status": "active"},
        },
    }

    def write_json(self, state=None) -> str:
        path = os.path.join(self.dir, "data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.STATE if state is None else state, f)
        return path

    def test_keeps_ids_and_continues_numbering(self):
        self.assertEqual(migrate(self.write_json(), self.apartments_db, self.bookings_db), (2, 2))
        svc = open_service(self.apartments_db, self.bookings_db)
        self.assertEqual(svc.get_apartment(2)["name"], "Loft")
        self.assertEqual(svc.get_apartment(3)["price"], 75.5)
        self.assertEqual(svc.get_booking(1)["status"], "cancelled")
        self.assertEqual([b["id"] for b in svc.list_bookings(apt_id=3)], [2])
        self.assertEqual(svc.add_apartment("New", "x")["id"], 4)
        self.assertEqual(svc.create_booking(2, "Cy", "2026-12-01", "2026-12-02")["id"], 3)
        with self.assertRaises(OverlapError):
            svc.create_booking(3, "Dee", "2026-11-02", "2026-11-03")

    def test_deleted_ids_stay_unused(self):
        state = {**self.STATE, "apartments": {}, "bookings": {}}
        migrate(self.write_json(state), self.apartments_db, self.bookings_db)
        svc = open_service(self.apartments_db, self.bookings_db)
        self.assertEqual(svc.add_apartment("New", "x")["id"], 4)

    def test_refuses_non_empty_databases(self):
        path = self.write_json()
        migrate(path, self.apartments_db, self.bookings_db)
        with self.assertRaisesRegex(MigrationError, "already contains apartments"):
            migrate(path, self.apartments_db, self.bookings_db)
        fresh_apartments = os.path.join(self.dir, "fresh.db")
        with self.assertRaisesRegex(MigrationError, "already contains bookings"):
            migrate(path, fresh_apartments, self.bookings_db)
        # Nothing was written to the fresh database before the check failed.
        self.assertEqual(ApartmentRepo(fresh_apartments).list(), [])

    def run_main(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_command_line(self):
        code, out, _ = self.run_main(self.write_json(), "--apartments-db", self.apartments_db,
                                     "--bookings-db", self.bookings_db)
        self.assertEqual(code, 0)
        self.assertIn("Migrated 2 apartments", out)
        code, _, err = self.run_main(self.write_json(), "--apartments-db", self.apartments_db,
                                     "--bookings-db", self.bookings_db)
        self.assertEqual(code, 1)
        self.assertIn("already contains", err)
        code, _, err = self.run_main(os.path.join(self.dir, "missing.json"))
        self.assertEqual(code, 1)
        self.assertIn("Error", err)


if __name__ == "__main__":
    unittest.main()

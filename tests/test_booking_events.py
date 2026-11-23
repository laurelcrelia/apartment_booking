import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from functools import partial

from bookings_service.migrate import migrate
from bookings_service.repos import BookingRepo
from apartments_service.consumer import handle_booking_event, on_message
from apartments_service.repo import ApartmentRepo
from common.events import BOOKING_CANCELLED, BOOKING_CHANGED, BOOKING_CREATED, encode, new_event
from common.relay import Relay
from common.worker import run_tasks
from devstack import LocalPublisher
from tests.helpers import Services


def booking_event(event_type, booking_id=1, version=1, **fields):
    data = {"id": booking_id, "apartment_id": 7, "check_in": "2026-11-01", "check_out": "2026-11-05",
            "status": "cancelled" if event_type == BOOKING_CANCELLED else "active", "version": version, **fields}
    return new_event(event_type, data)


class BookingOutboxTests(unittest.TestCase):
    def setUp(self):
        self.repo = BookingRepo(":memory:")

    def events(self):
        return [(e["type"], e["data"]) for _, e in self.repo.outbox.pending()]

    def test_every_change_writes_an_event_without_the_guest(self):
        with self.repo.writing() as table:
            b = table.insert(7, "Ann", "2026-11-01", "2026-11-05", "active")
            table.update(b["id"], check_out="2026-11-06", guest="Bob")
            table.update(b["id"], status="cancelled")
        base = {"id": 1, "apartment_id": 7, "check_in": "2026-11-01"}
        self.assertEqual(self.events(), [
            (BOOKING_CREATED, {**base, "check_out": "2026-11-05", "status": "active", "version": 1}),
            (BOOKING_CHANGED, {**base, "check_out": "2026-11-06", "status": "active", "version": 2}),
            (BOOKING_CANCELLED, {**base, "check_out": "2026-11-06", "status": "cancelled", "version": 3}),
        ])
        self.assertNotIn("Bob", json.dumps(self.repo.outbox.pending()))

    def test_api_shape_has_no_version(self):
        with self.repo.writing() as table:
            b = table.insert(7, "Ann", "2026-11-01", "2026-11-05", "active")
        self.assertNotIn("version", b)

    def test_failed_change_writes_no_event(self):
        with self.assertRaises(RuntimeError):
            with self.repo.writing() as table:
                table.insert(7, "Ann", "2026-11-01", "2026-11-05", "active")
                raise RuntimeError("rolled back")
        self.assertEqual(self.events(), [])


class UpgradeTests(unittest.TestCase):
    """A bookings database written before booking events existed."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "bookings.db")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, apartment_id INTEGER"
                         " NOT NULL, guest TEXT NOT NULL DEFAULT '', check_in TEXT NOT NULL,"
                         " check_out TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active')")
            conn.execute("INSERT INTO bookings (apartment_id, guest, check_in, check_out)"
                         " VALUES (7, 'Ann', '2026-11-01', '2026-11-05')")

    def test_version_column_is_added_and_existing_bookings_are_announced_once(self):
        repo = BookingRepo(self.path)
        with repo.writing() as table:
            self.assertEqual(table.update(1, check_out="2026-11-06")["check_out"], "2026-11-06")
        published = []
        relay = Relay(repo.outbox, LocalPublisher(published.append))
        relay.publish_pending()
        self.assertEqual([(e["type"], e["data"]["version"]) for e in published],
                         [(BOOKING_CHANGED, 2), (BOOKING_CREATED, 2)])  # the change, then the snapshot
        self.assertEqual(BookingRepo(self.path).outbox.snapshot_once(), 0)

    def test_opening_twice_is_fine(self):
        BookingRepo(self.path)
        BookingRepo(self.path)


class ApartmentsConsumerTests(unittest.TestCase):
    def setUp(self):
        self.repo = ApartmentRepo(":memory:")

    def replica(self):
        return {b["id"]: b for b in self.repo.bookings.list()}

    def test_created_changed_cancelled(self):
        self.assertTrue(handle_booking_event(self.repo, booking_event(BOOKING_CREATED)))
        handle_booking_event(self.repo, booking_event(BOOKING_CHANGED, version=2, check_out="2026-11-09"))
        self.assertEqual(self.replica()[1]["check_out"], "2026-11-09")
        handle_booking_event(self.repo, booking_event(BOOKING_CANCELLED, version=3))
        self.assertEqual((self.replica()[1]["status"], self.replica()[1]["version"]), ("cancelled", 3))

    def test_redelivery_and_old_versions_change_nothing(self):
        event = booking_event(BOOKING_CHANGED, version=3, check_out="2026-11-09")
        self.assertTrue(handle_booking_event(self.repo, event))
        self.assertFalse(handle_booking_event(self.repo, event))
        self.assertFalse(handle_booking_event(self.repo, booking_event(BOOKING_CREATED, version=1)))
        self.assertEqual(self.replica()[1]["check_out"], "2026-11-09")

    def test_late_create_does_not_undo_a_cancellation(self):
        handle_booking_event(self.repo, booking_event(BOOKING_CANCELLED, version=2))
        handle_booking_event(self.repo, booking_event(BOOKING_CREATED, version=1))
        self.assertEqual(self.replica()[1]["status"], "cancelled")

    def test_unknown_types_are_recorded_and_ignored(self):
        event = booking_event(BOOKING_CREATED)
        event["type"] = "booking.renamed"
        self.assertFalse(handle_booking_event(self.repo, event))
        self.assertEqual(self.replica(), {})

    def test_on_message(self):
        incomplete = booking_event(BOOKING_CREATED, booking_id=2)
        del incomplete["data"]["check_out"]
        with self.assertLogs("apartments_service.consumer", logging.INFO) as logs:
            on_message(self.repo, encode(booking_event(BOOKING_CREATED, booking_id=5)))
            on_message(self.repo, b"not json")
            on_message(self.repo, encode(incomplete))
        self.assertEqual(list(self.replica()), [5])
        self.assertIn("applied booking.created for booking 5", logs.output[0])
        self.assertIn("dropping malformed event", logs.output[1])
        self.assertIn("no check_out", logs.output[2])


class BothWaysTests(unittest.TestCase):
    def test_booking_changes_reach_the_apartments_side_right_away(self):
        svc = Services()
        svc.add_apartment("Loft", "x")
        b = svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        replica = svc.apartments_repo.bookings
        self.assertEqual([(r["id"], r["status"]) for r in replica.list()], [(b["id"], "active")])
        svc.change_booking(b["id"], check_out="2026-11-07")
        self.assertEqual(replica.list()[0]["check_out"], "2026-11-07")
        svc.cancel_booking(b["id"])
        self.assertEqual(replica.list()[0]["status"], "cancelled")

    def test_imported_bookings_are_announced(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data.json")
            with open(data, "w") as f:
                json.dump({"next_apartment_id": 2, "next_booking_id": 2,
                           "apartments": {"1": {"id": 1, "name": "Loft", "address": "", "rooms": 1, "price": 0}},
                           "bookings": {"1": {"id": 1, "apartment_id": 1, "guest": "Ann", "check_in": "2026-11-01",
                                              "check_out": "2026-11-05", "status": "active"}}}, f)
            dbs = os.path.join(tmp, "apartments.db"), os.path.join(tmp, "bookings.db")
            migrate(data, *dbs)
            svc = Services(*dbs)
            self.assertEqual([r["id"] for r in svc.apartments_repo.bookings.list()], [1])


class WorkerModuleTests(unittest.TestCase):
    def test_workers_import_and_use_distinct_heartbeats(self):
        import bookings_service.worker as bookings_worker
        import apartments_service.worker as apartments_worker
        files = [apartments_worker.RELAY_HEARTBEAT, apartments_worker.CONSUMER_HEARTBEAT,
                 bookings_worker.RELAY_HEARTBEAT, bookings_worker.CONSUMER_HEARTBEAT]
        self.assertEqual(len(set(files)), 4)
        compose_file = os.path.join(os.path.dirname(__file__), "..", "compose.yaml")
        if not os.path.exists(compose_file):
            self.skipTest("compose.yaml isn't in the Docker test image")
        with open(compose_file) as f:
            compose = f.read()
        for path in files:  # the Docker health checks look at the same files
            self.assertIn(path, compose)


class RunTasksTests(unittest.TestCase):
    def test_returns_the_first_task_that_stops(self):
        forever = threading.Event()
        with self.assertLogs("common.worker", logging.ERROR) as logs:
            stopped = run_tasks({"relay": forever.wait, "consumer": partial(time.sleep, 0.05)},
                                check_every=0.01)
        self.assertEqual(stopped, "consumer")
        self.assertIn("consumer stopped", logs.output[-1])

    def test_a_crashing_task_counts_as_stopped(self):
        def crash():
            raise RuntimeError("broker gone for good")
        with self.assertLogs("common.worker", logging.ERROR) as logs:
            self.assertEqual(run_tasks({"relay": crash}, check_every=0.01), "relay")
        self.assertIn("relay crashed", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()

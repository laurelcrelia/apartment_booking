import json
import logging
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from functools import partial

from apartment_booking.consumer import handle_event, on_message
from apartment_booking.inprocess import LocalPublisher
from apartment_booking.repos import BookingRepo
from apartment_booking.service import BookingService, open_service
from apartments_service.repo import ApartmentRepo, enqueue_snapshot
from apartments_service.service import ApartmentService
from common.errors import NotFoundError, ServiceUnavailableError
from common.relay import Relay
from common.events import (APARTMENT_CREATED, APARTMENT_DELETED, APARTMENT_UPDATED, decode, encode,
                           new_event)


class RecordingPublisher:
    def __init__(self, fail_after=None):
        self.events, self.fail_after = [], fail_after

    def publish(self, event):
        if self.fail_after is not None and len(self.events) >= self.fail_after:
            raise ConnectionError("broker gone")
        self.events.append(event)


def apartment_event(event_type, apt_id=1, version=1, **fields):
    data = {"id": apt_id, "version": version}
    if event_type != APARTMENT_DELETED:
        data.update({"name": "Loft", "address": "x", "rooms": 2, "price": 80.0, **fields})
    return new_event(event_type, data)


class EnvelopeTests(unittest.TestCase):
    def test_round_trip(self):
        event = new_event(APARTMENT_CREATED, {"id": 1, "version": 1, "name": "Loft"})
        self.assertEqual(decode(encode(event)), event)
        self.assertEqual(len(event["event_id"]), 36)
        self.assertTrue(event["occurred_at"].endswith("+00:00"))

    def test_rejects_malformed(self):
        for body in [b"not json", b"[]", b'{"event_id": "e", "type": "t"}',
                     b'{"type": "t", "data": {"id": 1, "version": 1}}',
                     b'{"event_id": "e", "type": "t", "data": {"id": "1", "version": 1}}',
                     b'{"event_id": "e", "type": "t", "data": {"id": 1, "version": true}}']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                decode(body)


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.repo = ApartmentRepo(":memory:")
        self.publisher = RecordingPublisher()
        self.relay = Relay(self.repo.outbox, self.publisher)

    def published(self):
        self.relay.publish_pending()
        return [(e["type"], e["data"]) for e in self.publisher.events]

    def test_every_change_writes_an_event_with_its_version(self):
        self.repo.add("Loft", "x", 2, 80)
        self.repo.update(1, price=90)
        self.repo.update(1)  # no change, no event
        self.repo.delete(1)
        self.assertEqual(self.published(), [
            (APARTMENT_CREATED, {"id": 1, "name": "Loft", "address": "x", "rooms": 2, "price": 80.0, "version": 1}),
            (APARTMENT_UPDATED, {"id": 1, "name": "Loft", "address": "x", "rooms": 2, "price": 90.0, "version": 2}),
            (APARTMENT_DELETED, {"id": 1, "version": 3}),
        ])

    def test_missing_apartments_write_no_events(self):
        self.assertIsNone(self.repo.update(5, name="x"))
        self.assertFalse(self.repo.delete(5))
        self.assertEqual(self.published(), [])

    def test_published_events_are_not_sent_again(self):
        self.repo.add("Loft", "x", 1, 0)
        self.assertEqual(self.relay.publish_pending(), 1)
        self.assertEqual(self.relay.publish_pending(), 0)
        self.assertEqual(self.repo.outbox.pending(), [])

    def test_publishing_in_batches(self):
        for i in range(5):
            self.repo.add(f"A{i}", "x", 1, 0)
        self.assertEqual(len(self.repo.outbox.pending(limit=2)), 2)
        self.assertEqual(self.relay.publish_pending(), 5)

    def test_failed_publish_keeps_the_event_pending(self):
        self.repo.add("A", "x", 1, 0)
        self.repo.add("B", "x", 1, 0)
        failing = Relay(self.repo.outbox, RecordingPublisher(fail_after=1))
        with self.assertRaises(ConnectionError):
            failing.publish_pending()
        self.assertEqual([e["data"]["name"] for _, e in self.repo.outbox.pending()], ["B"])
        self.relay.publish_pending()
        self.assertEqual([e["data"]["name"] for e in self.publisher.events], ["B"])

    def test_change_and_event_are_one_transaction(self):
        with self.assertRaises(Exception):
            self.repo.add("Loft", "x", None, 0)  # violates NOT NULL
        self.assertEqual(self.repo.list(), [])
        self.assertEqual(self.repo.outbox.pending(), [])

    def test_snapshot_of_existing_apartments_happens_once(self):
        with self.repo.db.transaction() as conn:  # as if upgraded from before events existed
            conn.execute("DELETE FROM outbox_state")
            conn.execute("INSERT INTO apartments (name, address, rooms, price, version)"
                         " VALUES ('Old', 'x', 1, 50, 4)")
        self.assertEqual(self.published(), [
            (APARTMENT_CREATED, {"id": 1, "name": "Old", "address": "x", "rooms": 1, "price": 50.0, "version": 4})])
        self.assertEqual(self.repo.outbox.snapshot_once(), 0)
        with self.repo.db.transaction() as conn:
            self.assertEqual(enqueue_snapshot(conn), 1)  # explicit snapshots are always allowed


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.repo = BookingRepo(":memory:")

    def replica(self, apt_id=1):
        with self.repo.reading() as table:
            return table.replica_get(apt_id)

    def test_created_updated_deleted(self):
        self.assertTrue(handle_event(self.repo, apartment_event(APARTMENT_CREATED)))
        self.assertEqual(self.replica(), {"id": 1, "name": "Loft", "address": "x", "rooms": 2,
                                          "price": 80.0, "version": 1, "deleted": 0})
        handle_event(self.repo, apartment_event(APARTMENT_UPDATED, version=2, rooms=4))
        self.assertEqual((self.replica()["rooms"], self.replica()["version"]), (4, 2))
        handle_event(self.repo, apartment_event(APARTMENT_DELETED, version=3))
        self.assertEqual((self.replica()["deleted"], self.replica()["version"]), (1, 3))

    def test_redelivered_event_is_applied_once(self):
        event = apartment_event(APARTMENT_CREATED)
        self.assertTrue(handle_event(self.repo, event))
        self.assertFalse(handle_event(self.repo, event))

    def test_older_versions_are_ignored(self):
        handle_event(self.repo, apartment_event(APARTMENT_UPDATED, version=3, name="New"))
        self.assertFalse(handle_event(self.repo, apartment_event(APARTMENT_UPDATED, version=2, name="Old")))
        self.assertFalse(handle_event(self.repo, apartment_event(APARTMENT_UPDATED, version=3, name="Same")))
        self.assertEqual(self.replica()["name"], "New")

    def test_late_create_does_not_resurrect_a_deleted_apartment(self):
        handle_event(self.repo, apartment_event(APARTMENT_DELETED, version=2))
        self.assertFalse(handle_event(self.repo, apartment_event(APARTMENT_CREATED, version=1)))
        self.assertEqual(self.replica()["deleted"], 1)

    def test_unknown_event_types_are_recorded_and_ignored(self):
        event = apartment_event(APARTMENT_CREATED)
        event["type"] = "apartment.renamed"
        self.assertFalse(handle_event(self.repo, event))
        self.assertIsNone(self.replica())

    def test_on_message(self):
        with self.assertLogs("apartment_booking.consumer", logging.INFO) as logs:
            on_message(self.repo, encode(apartment_event(APARTMENT_CREATED, apt_id=7)))
            on_message(self.repo, b"{broken")
        self.assertEqual(self.replica(7)["name"], "Loft")
        self.assertIn("applied apartment.created for apartment 7", logs.output[0])
        self.assertIn("dropping malformed event", logs.output[1])


class ReplicaInBookingRulesTests(unittest.TestCase):
    """BookingService against an apartments service whose events arrive only when delivered."""

    def setUp(self):
        self.apartments_repo = ApartmentRepo(":memory:")
        self.apartments = ApartmentService(self.apartments_repo)
        self.bookings = BookingRepo(":memory:")
        self.svc = BookingService(self.bookings, self.apartments)
        self.relay = Relay(self.apartments_repo.outbox, LocalPublisher(partial(handle_event, self.bookings)))

    def search(self, **kw):
        return [a["id"] for a in self.svc.search_available("2026-11-01", "2026-11-02", **kw)]

    def test_search_sees_apartments_once_events_arrive(self):
        self.apartments.add("Loft", "x", rooms=2)
        self.assertEqual(self.search(), [])
        self.relay.publish_pending()
        self.assertEqual(self.search(), [1])
        self.assertEqual(self.search(min_rooms=3), [])
        self.apartments.update(1, rooms=3)
        self.relay.publish_pending()
        self.assertEqual(self.search(min_rooms=3), [1])
        self.assertEqual(self.svc.search_available("2026-11-01", "2026-11-02")[0]["rooms"], 3)

    def test_booking_a_brand_new_apartment_reads_through(self):
        self.apartments.add("Loft", "x")
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")  # before any event
        with self.bookings.reading() as table:
            self.assertEqual(table.replica_get(1)["version"], 0)
        self.relay.publish_pending()
        with self.bookings.reading() as table:
            self.assertEqual(table.replica_get(1)["version"], 1)

    def test_deleted_apartment_is_not_bookable_once_known(self):
        self.apartments.add("Loft", "x")
        self.apartments.delete(1)
        self.relay.publish_pending()
        self.apartments = None  # the replica alone must answer
        with self.assertRaisesRegex(NotFoundError, "Apartment 1 not found"):
            self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")

    def test_booking_works_while_apartments_service_is_down(self):
        self.apartments.add("Loft", "x")
        self.relay.publish_pending()

        class Down:
            def __getattr__(self, name):
                def fail(*args, **kwargs):
                    raise ServiceUnavailableError("down")
                return fail

        self.svc.apartments = Down()
        self.assertEqual(self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")["id"], 1)
        self.assertEqual(self.search(), [])
        self.svc.change_booking(1, apt_id=1, check_out="2026-11-06")
        with self.assertRaises(ServiceUnavailableError):
            self.svc.create_booking(2, "Bob", "2026-11-01", "2026-11-05")  # unknown and can't ask


class InProcessTests(unittest.TestCase):
    def test_replica_is_updated_right_away(self):
        svc = open_service()
        svc.add_apartment("Loft", "x")
        self.assertEqual([a["id"] for a in svc.search_available("2026-11-01", "2026-11-02")], [1])
        svc.remove_apartment(1)
        self.assertEqual(svc.search_available("2026-11-01", "2026-11-02"), [])

    def test_existing_apartments_reach_the_replica_on_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            apartments_db = os.path.join(tmp, "apartments.db")
            # A database written by the version before events: no outbox tables.
            with closing(sqlite3.connect(apartments_db)) as conn, conn:
                conn.execute("CREATE TABLE apartments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,"
                             " address TEXT, rooms INTEGER, price REAL, version INTEGER DEFAULT 1)")
                conn.execute("INSERT INTO apartments (name, address, rooms, price) VALUES ('Old', 'x', 1, 0)")
            svc = open_service(apartments_db, os.path.join(tmp, "bookings.db"))
            self.assertEqual([a["name"] for a in svc.search_available("2026-11-01", "2026-11-02")], ["Old"])
            # A fresh database needs no snapshot: new apartments announce themselves.
            self.assertEqual(ApartmentRepo(os.path.join(tmp, "new.db")).outbox.snapshot_once(), 0)

    def test_local_publisher_rejects_non_json(self):
        publisher = LocalPublisher(partial(handle_event, BookingRepo(":memory:")))
        with self.assertRaises(TypeError):
            publisher.publish({**apartment_event(APARTMENT_CREATED), "occurred_at": object()})
        json.dumps(apartment_event(APARTMENT_CREATED))  # the normal case serializes fine


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import devstack
from booking_cli.cli import main
from common.errors import BookingError, ConflictError, NotFoundError, OverlapError
from tests.helpers import Services


class ApartmentTests(unittest.TestCase):
    def setUp(self):
        self.svc = Services()

    def test_add_view_list(self):
        a = self.svc.add_apartment("Loft", "1 Main St", rooms=2, price=80)
        self.assertEqual(a["id"], 1)
        self.assertEqual(self.svc.get_apartment(1)["name"], "Loft")
        self.svc.add_apartment("Studio", "2 Main St")
        self.assertEqual([x["id"] for x in self.svc.list_apartments()], [1, 2])

    def test_update(self):
        self.svc.add_apartment("Loft", "1 Main St")
        a = self.svc.update_apartment(1, price=99.5, rooms=3)
        self.assertEqual((a["price"], a["rooms"], a["name"]), (99.5, 3, "Loft"))

    def test_validation(self):
        with self.assertRaises(BookingError):
            self.svc.add_apartment("  ", "x")
        with self.assertRaises(BookingError):
            self.svc.add_apartment("A", "x", rooms=0)
        with self.assertRaises(BookingError):
            self.svc.add_apartment("A", "x", price=-1)

    def test_update_validation(self):
        self.svc.add_apartment("Loft", "1 Main St")
        for changes in ({"name": " "}, {"rooms": 0}, {"price": -1}):
            with self.subTest(changes=changes), self.assertRaises(BookingError):
                self.svc.update_apartment(1, **changes)
        with self.assertRaises(NotFoundError):
            self.svc.update_apartment(9, name="x")
        a = self.svc.update_apartment(1, name=" Big Loft ", address="2 Main St")
        self.assertEqual((a["name"], a["address"]), ("Big Loft", "2 Main St"))

    def test_remove(self):
        self.svc.add_apartment("Loft", "x")
        self.svc.remove_apartment(1)
        with self.assertRaises(NotFoundError):
            self.svc.get_apartment(1)

    def test_remove_blocked_by_active_booking(self):
        self.svc.add_apartment("Loft", "x")
        b = self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        with self.assertRaises(BookingError):
            self.svc.remove_apartment(1)
        self.svc.cancel_booking(b["id"])
        self.svc.remove_apartment(1)

    def test_ids_not_reused(self):
        self.svc.add_apartment("A", "x")
        self.svc.remove_apartment(1)
        self.assertEqual(self.svc.add_apartment("B", "y")["id"], 2)


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.svc = Services()
        self.svc.add_apartment("Loft", "x")
        self.svc.add_apartment("Studio", "y")

    def test_create_and_view(self):
        b = self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        self.assertEqual(self.svc.get_booking(b["id"])["status"], "active")

    def test_invalid_dates(self):
        with self.assertRaises(BookingError):
            self.svc.create_booking(1, "Ann", "2026-11-05", "2026-11-05")
        with self.assertRaises(BookingError):
            self.svc.create_booking(1, "Ann", "2026-11-05", "2026-11-01")
        with self.assertRaises(BookingError):
            self.svc.create_booking(1, "Ann", "11/01/2026", "2026-11-05")

    def test_unknown_apartment(self):
        with self.assertRaises(NotFoundError):
            self.svc.create_booking(99, "Ann", "2026-11-01", "2026-11-05")

    def test_overlap_rejected(self):
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        for ci, co in [("2026-11-01", "2026-11-05"), ("2026-10-30", "2026-11-02"),
                       ("2026-11-04", "2026-11-10"), ("2026-11-02", "2026-11-03"),
                       ("2026-10-01", "2026-12-01")]:
            with self.subTest(ci=ci, co=co), self.assertRaises(OverlapError):
                self.svc.create_booking(1, "Bob", ci, co)

    def test_back_to_back_allowed(self):
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        self.svc.create_booking(1, "Bob", "2026-11-05", "2026-11-08")
        self.svc.create_booking(1, "Cy", "2026-10-28", "2026-11-01")

    def test_same_dates_other_apartment_allowed(self):
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        self.svc.create_booking(2, "Bob", "2026-11-01", "2026-11-05")

    def test_cancel_frees_dates(self):
        b = self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        self.svc.cancel_booking(b["id"])
        self.svc.create_booking(1, "Bob", "2026-11-01", "2026-11-05")
        with self.assertRaises(BookingError):
            self.svc.cancel_booking(b["id"])

    def test_change_dates_can_overlap_itself(self):
        b = self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        c = self.svc.change_booking(b["id"], check_out="2026-11-07")
        self.assertEqual(c["check_out"], "2026-11-07")

    def test_change_rejects_overlap_with_other(self):
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        b = self.svc.create_booking(1, "Bob", "2026-11-10", "2026-11-12")
        with self.assertRaises(OverlapError):
            self.svc.change_booking(b["id"], check_in="2026-11-04")
        # Unchanged after failure.
        self.assertEqual(self.svc.get_booking(b["id"])["check_in"], "2026-11-10")

    def test_change_apartment(self):
        self.svc.create_booking(2, "Ann", "2026-11-01", "2026-11-05")
        b = self.svc.create_booking(1, "Bob", "2026-11-01", "2026-11-05")
        with self.assertRaises(OverlapError):
            self.svc.change_booking(b["id"], apt_id=2)
        self.svc.cancel_booking(1)
        self.assertEqual(self.svc.change_booking(b["id"], apt_id=2)["apartment_id"], 2)

    def test_cannot_change_cancelled(self):
        b = self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        self.svc.cancel_booking(b["id"])
        with self.assertRaises(BookingError):
            self.svc.change_booking(b["id"], guest="Bob")

    def test_list_filters(self):
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")
        b = self.svc.create_booking(2, "Bob", "2026-11-01", "2026-11-05")
        self.svc.cancel_booking(b["id"])
        self.assertEqual(len(self.svc.list_bookings()), 1)
        self.assertEqual(len(self.svc.list_bookings(include_cancelled=True)), 2)
        self.assertEqual(len(self.svc.list_bookings(apt_id=2, include_cancelled=True)), 1)
        self.assertEqual(len(self.svc.list_bookings(guest="ann")), 1)


class ConflictTests(unittest.TestCase):
    """Rule violations that depend on existing data are ConflictErrors (HTTP 409)."""

    def setUp(self):
        self.svc = Services()
        self.svc.add_apartment("Loft", "1 Main St")
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")

    def test_overlap_is_conflict(self):
        with self.assertRaises(ConflictError):
            self.svc.create_booking(1, "Bob", "2026-11-02", "2026-11-03")

    def test_remove_with_active_booking_is_conflict(self):
        with self.assertRaises(ConflictError):
            self.svc.remove_apartment(1)

    def test_cancelled_booking_conflicts(self):
        self.svc.cancel_booking(1)
        with self.assertRaises(ConflictError):
            self.svc.cancel_booking(1)
        with self.assertRaises(ConflictError):
            self.svc.change_booking(1, guest="Bob")

    def test_invalid_input_is_not_conflict(self):
        with self.assertRaises(BookingError) as ctx:
            self.svc.create_booking(1, "Bob", "2026-12-05", "2026-12-01")
        self.assertNotIsInstance(ctx.exception, ConflictError)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.svc = Services()
        self.svc.add_apartment("Loft", "x", rooms=1)
        self.svc.add_apartment("Studio", "y", rooms=3)
        self.svc.create_booking(1, "Ann", "2026-11-01", "2026-11-05")

    def ids(self, *args, **kw):
        return [a["id"] for a in self.svc.search_available(*args, **kw)]

    def test_search(self):
        self.assertEqual(self.ids("2026-11-03", "2026-11-04"), [2])
        self.assertEqual(self.ids("2026-11-05", "2026-11-06"), [1, 2])
        self.assertEqual(self.ids("2026-10-01", "2026-11-01"), [1, 2])
        self.assertEqual(self.ids("2026-11-05", "2026-11-06", min_rooms=2), [2])

    def test_cancelled_does_not_block(self):
        self.svc.cancel_booking(1)
        self.assertEqual(self.ids("2026-11-03", "2026-11-04"), [1, 2])

    def test_invalid_range(self):
        with self.assertRaises(BookingError):
            self.svc.search_available("2026-11-05", "2026-11-01")


class CliTests(unittest.TestCase):
    """The CLI against the running app (devstack), through the public API."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dbs = os.path.join(tmp.name, "apartments.db"), os.path.join(tmp.name, "bookings.db")
        self.stack = devstack.start(*self.dbs)
        self.addCleanup(self.stack.stop)

    def cli(self, *argv, api=None):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([*argv, "--api", api or self.stack.url])
        return code, out.getvalue(), err.getvalue()

    def test_end_to_end_persists(self):
        self.assertEqual(self.cli("apartment", "add", "--name", "Loft", "--address", "x", "--rooms", "2")[0], 0)
        code, out, _ = self.cli("booking", "create", "--apartment", "1", "--from", "2026-11-01",
                                "--to", "2026-11-05", "--guest", "Ann")
        self.assertEqual(code, 0)
        self.assertIn("Created booking", out)
        code, _, err = self.cli("booking", "create", "--apartment", "1", "--from", "2026-11-03",
                                "--to", "2026-11-06")
        self.assertEqual(code, 1)
        self.assertIn("already booked", err)
        _, out, _ = self.cli("apartment", "search", "--from", "2026-11-03", "--to", "2026-11-04")
        self.assertIn("No apartments available", out)
        _, out, _ = self.cli("booking", "change", "1", "--to", "2026-11-07", "--json")
        self.assertIn('"check_out": "2026-11-07"', out)
        # The data really lives in the app's databases.
        self.stack.stop()
        restarted = devstack.start(*self.dbs)
        self.addCleanup(restarted.stop)
        self.assertEqual(restarted.call("GET", "/api/bookings/1")["check_out"], "2026-11-07")

    def test_every_command(self):
        self.cli("apartment", "add", "--name", "Loft", "--address", "x", "--price", "80")
        self.assertIn("[1] Loft | x | rooms: 1 | 80.00/night", self.cli("apartment", "list")[1])
        self.assertIn("Loft", self.cli("apartment", "view", "1")[1])
        self.assertIn("rooms: 3", self.cli("apartment", "update", "1", "--rooms", "3")[1])
        self.cli("booking", "create", "--apartment", "1", "--from", "2026-11-01", "--to", "2026-11-05")
        self.assertIn("[1] apartment 1 | - | 2026-11-01 -> 2026-11-05 | active",
                      self.cli("booking", "list", "--apartment", "1")[1])
        self.assertIn("active", self.cli("booking", "view", "1")[1])
        code, _, err = self.cli("apartment", "remove", "1")
        self.assertEqual(code, 1)
        self.assertIn("active bookings", err)
        self.assertIn("Cancelled booking", self.cli("booking", "cancel", "1")[1])
        self.assertIn("No bookings", self.cli("booking", "list")[1])
        self.assertIn("cancelled", self.cli("booking", "list", "--all", "--guest", "")[1])
        self.assertIn("Removed apartment: [1] Loft", self.cli("apartment", "remove", "1")[1])
        self.assertIn("No apartments", self.cli("apartment", "list")[1])

    def test_unreachable_app(self):
        code, _, err = self.cli("apartment", "list", api="http://127.0.0.1:9")
        self.assertEqual(code, 1)
        self.assertIn("Can't reach the app at http://127.0.0.1:9", err)

    def test_help_lists_commands(self):
        code, out, _ = self.cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("booking create --apartment ID --from DATE --to DATE", out)
        self.assertIn("apartment search --from DATE --to DATE", out)
        self.assertIn("--api URL", out)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from unittest import mock

from apartments_service.app import create_app
from apartments_service.consumer import handle_booking_event
from apartments_service.repo import ApartmentRepo
from apartments_service.service import ApartmentService
from common.events import new_event


class FakeBookings:
    """Stands in for the booking service in the delete check."""

    def __init__(self):
        self.active = {}  # apartment id -> booking ids

    def active_bookings(self, apt_id):
        return [{"id": b} for b in self.active.get(apt_id, [])]


def booking_event(booking_id, apt_id, check_in, check_out, status="active", version=1):
    return new_event("booking.created", {"id": booking_id, "apartment_id": apt_id, "check_in": check_in,
                                         "check_out": check_out, "status": status, "version": version})


class ApartmentsServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = ApartmentRepo(":memory:")
        self.bookings = FakeBookings()
        self.client = create_app(ApartmentService(self.repo, self.bookings)).test_client()

    def add(self, **fields):
        r = self.client.post("/api/apartments", json={"name": "Loft", "address": "1 Beach Rd", **fields})
        self.assertEqual(r.status_code, 201, r.json)
        return r.json

    def assertError(self, response, status, code, message_part=""):
        self.assertEqual(response.status_code, status, response.json)
        self.assertEqual(response.json["error"]["code"], code)
        self.assertIn(message_part, response.json["error"]["message"])


class CrudTests(ApartmentsServiceTestCase):
    def test_create_get_list(self):
        r = self.client.post("/api/apartments", json={"name": "Loft", "address": "x", "rooms": 2, "price": 80})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.headers["Location"], "/api/apartments/1")
        self.assertEqual(r.json, {"id": 1, "name": "Loft", "address": "x", "rooms": 2, "price": 80.0})
        self.assertEqual(self.client.get("/api/apartments/1").json, r.json)
        self.add(name="Studio")
        self.assertEqual([a["name"] for a in self.client.get("/api/apartments").json], ["Loft", "Studio"])

    def test_min_rooms(self):
        self.add(rooms=1)
        self.add(rooms=3)
        self.assertEqual([a["id"] for a in self.client.get("/api/apartments?min_rooms=2").json], [2])
        self.assertError(self.client.get("/api/apartments?min_rooms=0"), 400, "validation_error")

    def test_update_and_delete(self):
        self.add()
        r = self.client.patch("/api/apartments/1", json={"price": 95.5})
        self.assertEqual((r.status_code, r.json["price"]), (200, 95.5))
        self.assertEqual(self.client.delete("/api/apartments/1").status_code, 204)
        self.assertError(self.client.get("/api/apartments/1"), 404, "not_found", "Apartment 1")
        self.assertError(self.client.delete("/api/apartments/1"), 404, "not_found")

    def test_validation(self):
        self.assertError(self.client.post("/api/apartments", json={"name": " ", "address": "x"}),
                         400, "validation_error", "name is required")
        self.assertError(self.client.post("/api/apartments", json={"address": "x"}),
                         400, "validation_error", "Missing required field(s): name")
        self.add()
        self.assertError(self.client.patch("/api/apartments/1", json={"rooms": 0}),
                         400, "validation_error", "at least 1")
        self.assertError(self.client.post("/api/apartments", data="x", content_type="text/plain"),
                         415, "unsupported_media_type")

    def test_does_not_serve_bookings(self):
        self.assertError(self.client.get("/api/bookings"), 404, "not_found")

    def test_health_and_json_http_errors(self):
        self.assertEqual(self.client.get("/api/health").json, {"status": "ok"})
        self.assertError(self.client.put("/api/apartments"), 405, "method_not_allowed")


class DeleteCheckTests(ApartmentsServiceTestCase):
    def test_apartment_with_active_bookings_cannot_be_deleted(self):
        self.add()
        self.bookings.active[1] = [3, 5]
        self.assertError(self.client.delete("/api/apartments/1"), 409, "conflict",
                         "Apartment 1 has active bookings (3, 5); cancel them first")
        self.assertEqual(self.client.get("/api/apartments/1").status_code, 200)
        self.bookings.active[1] = []
        self.assertEqual(self.client.delete("/api/apartments/1").status_code, 204)

    def test_unknown_apartment_is_404_before_asking(self):
        self.bookings.active[9] = [1]
        self.assertError(self.client.delete("/api/apartments/9"), 404, "not_found")


class SearchTests(ApartmentsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.add(name="Small", rooms=1)
        self.add(name="Big", rooms=3)
        handle_booking_event(self.repo, booking_event(1, 1, "2026-11-01", "2026-11-05"))

    def search(self, query):
        r = self.client.get("/api/apartments?" + query)
        self.assertEqual(r.status_code, 200, r.json)
        return [a["id"] for a in r.json]

    def test_reads_the_bookings_replica(self):
        self.assertEqual(self.search("from=2026-11-03&to=2026-11-04"), [2])
        self.assertEqual(self.search("from=2026-11-05&to=2026-11-07"), [1, 2])  # back to back
        self.assertEqual(self.search("from=2026-12-01&to=2026-12-02&min_rooms=2"), [2])
        handle_booking_event(self.repo, booking_event(1, 1, "2026-11-01", "2026-11-05", "cancelled", 2))
        self.assertEqual(self.search("from=2026-11-03&to=2026-11-04"), [1, 2])

    def test_results_have_the_api_shape(self):
        r = self.client.get("/api/apartments?from=2026-12-01&to=2026-12-02")
        self.assertEqual(r.json[0], {"id": 1, "name": "Small", "address": "1 Beach Rd", "rooms": 1, "price": 0.0})

    def test_invalid_queries(self):
        for query, message in [("from=2026-11-01", "given together"),
                               ("from=2026-11-05&to=2026-11-01", "after check-in"),
                               ("from=soon&to=2026-11-01", "Invalid date")]:
            with self.subTest(query=query):
                self.assertError(self.client.get("/api/apartments?" + query), 400, "validation_error", message)


class ConfigurationTests(unittest.TestCase):
    def test_settings_come_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "apts.db")
            with mock.patch.dict(os.environ, {"APARTMENTS_DB": path, "BOOKINGS_URL": "http://bookings"}):
                app = create_app()
                app.test_client().post("/api/apartments", json={"name": "Loft", "address": "x"})
            self.assertEqual(ApartmentRepo(path).get(1)["name"], "Loft")
            self.assertEqual(app.extensions["apartment_service"].bookings.base_url, "http://bookings")

    def test_bookings_url_is_required(self):
        with mock.patch.dict(os.environ, {"APARTMENTS_DB": ":memory:"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "BOOKINGS_URL"):
                create_app()


if __name__ == "__main__":
    unittest.main()

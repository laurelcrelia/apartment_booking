import os
import tempfile
import unittest

from apartment_booking.storage import JsonStorage, MemoryStorage
from apartment_booking.web import create_app


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.client = create_app(MemoryStorage()).test_client()

    def add_apartment(self, **fields):
        body = {"name": "Loft", "address": "1 Beach Rd", **fields}
        r = self.client.post("/api/apartments", json=body)
        self.assertEqual(r.status_code, 201, r.json)
        return r.json

    def book(self, apartment_id, check_in, check_out, guest="Ann"):
        return self.client.post("/api/bookings", json={
            "apartment_id": apartment_id, "check_in": check_in,
            "check_out": check_out, "guest": guest})

    def assertError(self, response, status, code, message_part=""):
        self.assertEqual(response.status_code, status, response.json)
        self.assertEqual(response.json["error"]["code"], code)
        self.assertIn(message_part, response.json["error"]["message"])


class ApartmentApiTests(ApiTestCase):
    def test_create_returns_201_with_location(self):
        r = self.client.post("/api/apartments", json={
            "name": "Loft", "address": "1 Beach Rd", "rooms": 2, "price": 80})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.headers["Location"], "/api/apartments/1")
        self.assertEqual(r.json, {"id": 1, "name": "Loft", "address": "1 Beach Rd",
                                  "rooms": 2, "price": 80})

    def test_create_defaults(self):
        a = self.add_apartment()
        self.assertEqual((a["rooms"], a["price"]), (1, 0.0))

    def test_list_and_get(self):
        self.add_apartment(name="Loft")
        self.add_apartment(name="Studio")
        r = self.client.get("/api/apartments")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([a["name"] for a in r.json], ["Loft", "Studio"])
        self.assertEqual(self.client.get("/api/apartments/2").json["name"], "Studio")

    def test_get_unknown_is_404(self):
        self.assertError(self.client.get("/api/apartments/42"), 404, "not_found", "Apartment 42")

    def test_patch_changes_only_sent_fields(self):
        self.add_apartment(rooms=2, price=80)
        r = self.client.patch("/api/apartments/1", json={"price": 95.5})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json["name"], r.json["rooms"], r.json["price"]), ("Loft", 2, 95.5))

    def test_delete(self):
        self.add_apartment()
        r = self.client.delete("/api/apartments/1")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.data, b"")
        self.assertEqual(self.client.get("/api/apartments/1").status_code, 404)

    def test_delete_with_active_booking_is_409(self):
        self.add_apartment()
        self.book(1, "2026-11-01", "2026-11-05")
        self.assertError(self.client.delete("/api/apartments/1"), 409, "conflict", "active bookings")

    def test_delete_after_cancelling_bookings(self):
        self.add_apartment()
        self.book(1, "2026-11-01", "2026-11-05")
        self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertEqual(self.client.delete("/api/apartments/1").status_code, 204)

    def test_validation_errors(self):
        cases = [
            ({"address": "x"}, "Missing required field(s): name"),
            ({"name": " ", "address": "x"}, "name is required"),
            ({"name": "A", "address": "x", "rooms": 0}, "at least 1"),
            ({"name": "A", "address": "x", "rooms": 1.5}, "'rooms' must be an integer"),
            ({"name": "A", "address": "x", "rooms": True}, "'rooms' must be an integer"),
            ({"name": "A", "address": "x", "price": -1}, "cannot be negative"),
            ({"name": "A", "address": "x", "price": "10"}, "'price' must be a number"),
            ({"name": "A", "address": "x", "colour": "red"}, "Unknown field(s): colour"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                r = self.client.post("/api/apartments", json=body)
                self.assertError(r, 400, "validation_error", message)

    def test_body_must_be_json_object(self):
        r = self.client.post("/api/apartments", data="name=Loft",
                             content_type="application/x-www-form-urlencoded")
        self.assertError(r, 415, "unsupported_media_type")
        r = self.client.post("/api/apartments", data="{not json", content_type="application/json")
        self.assertError(r, 400, "validation_error", "JSON object")
        r = self.client.post("/api/apartments", json=["Loft"])
        self.assertError(r, 400, "validation_error", "JSON object")

    def test_http_errors_are_json(self):
        self.assertError(self.client.put("/api/apartments"), 405, "method_not_allowed")
        self.assertError(self.client.get("/api/nothing-here"), 404, "not_found")
        self.assertError(self.client.get("/api/apartments/abc"), 404, "not_found")


class SearchApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.add_apartment(name="Small", rooms=1)
        self.add_apartment(name="Big", rooms=3)
        self.book(1, "2026-11-01", "2026-11-05")

    def search(self, query):
        r = self.client.get("/api/apartments?" + query)
        self.assertEqual(r.status_code, 200, r.json)
        return [a["id"] for a in r.json]

    def test_excludes_booked_apartments(self):
        self.assertEqual(self.search("from=2026-11-03&to=2026-11-04"), [2])

    def test_back_to_back_is_available(self):
        self.assertEqual(self.search("from=2026-11-05&to=2026-11-07"), [1, 2])

    def test_min_rooms(self):
        self.assertEqual(self.search("from=2026-12-01&to=2026-12-02&min_rooms=2"), [2])
        self.assertEqual(self.search("min_rooms=2"), [2])

    def test_cancelled_booking_does_not_block(self):
        self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertEqual(self.search("from=2026-11-03&to=2026-11-04"), [1, 2])

    def test_invalid_queries(self):
        cases = [
            ("from=2026-11-01", "given together"),
            ("from=2026-11-05&to=2026-11-01", "after check-in"),
            ("from=yesterday&to=2026-11-01", "Invalid date"),
            ("min_rooms=two", "must be an integer"),
            ("min_rooms=0", "at least 1"),
        ]
        for query, message in cases:
            with self.subTest(query=query):
                r = self.client.get("/api/apartments?" + query)
                self.assertError(r, 400, "validation_error", message)


class BookingApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.add_apartment(name="Loft")
        self.add_apartment(name="Studio")

    def test_create_returns_201_with_location(self):
        r = self.book(1, "2026-11-01", "2026-11-05")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.headers["Location"], "/api/bookings/1")
        self.assertEqual(r.json, {"id": 1, "apartment_id": 1, "guest": "Ann",
                                  "check_in": "2026-11-01", "check_out": "2026-11-05",
                                  "status": "active"})
        self.assertEqual(self.client.get("/api/bookings/1").json, r.json)

    def test_guest_is_optional(self):
        r = self.client.post("/api/bookings", json={
            "apartment_id": 1, "check_in": "2026-11-01", "check_out": "2026-11-02"})
        self.assertEqual((r.status_code, r.json["guest"]), (201, ""))

    def test_overlap_is_409(self):
        self.book(1, "2026-11-01", "2026-11-05")
        self.assertError(self.book(1, "2026-11-04", "2026-11-06"), 409, "conflict", "already booked")

    def test_back_to_back_and_other_apartment_allowed(self):
        self.book(1, "2026-11-01", "2026-11-05")
        self.assertEqual(self.book(1, "2026-11-05", "2026-11-07").status_code, 201)
        self.assertEqual(self.book(2, "2026-11-01", "2026-11-05").status_code, 201)

    def test_create_errors(self):
        self.assertError(self.book(42, "2026-11-01", "2026-11-05"), 404, "not_found", "Apartment 42")
        self.assertError(self.book(1, "2026-11-05", "2026-11-05"), 400, "validation_error", "after check-in")
        self.assertError(self.book(1, "2026-13-01", "2026-11-05"), 400, "validation_error", "Invalid date")
        self.assertError(self.book("1", "2026-11-01", "2026-11-05"), 400, "validation_error", "must be an integer")
        r = self.client.post("/api/bookings", json={"apartment_id": 1})
        self.assertError(r, 400, "validation_error", "check_in, check_out")

    def test_list_filters(self):
        self.book(1, "2026-11-10", "2026-11-12", guest="Ann")
        self.book(2, "2026-11-01", "2026-11-03", guest="Bob")
        self.book(1, "2026-11-01", "2026-11-03", guest="Bob")
        self.client.patch("/api/bookings/3", json={"status": "cancelled"})

        def ids(query=""):
            r = self.client.get("/api/bookings" + query)
            self.assertEqual(r.status_code, 200, r.json)
            return [b["id"] for b in r.json]

        self.assertEqual(ids(), [2, 1])
        self.assertEqual(ids("?include_cancelled=true"), [2, 3, 1])
        self.assertEqual(ids("?apartment_id=1"), [1])
        self.assertEqual(ids("?guest=bob&include_cancelled=true"), [2, 3])
        self.assertError(self.client.get("/api/bookings?include_cancelled=yes"), 400, "validation_error")
        self.assertError(self.client.get("/api/bookings?apartment_id=x"), 400, "validation_error")

    def test_change_dates_apartment_and_guest(self):
        self.book(1, "2026-11-01", "2026-11-05")
        r = self.client.patch("/api/bookings/1", json={"check_in": "2026-11-03", "check_out": "2026-11-08"})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual((r.json["check_in"], r.json["check_out"]), ("2026-11-03", "2026-11-08"))
        r = self.client.patch("/api/bookings/1", json={"apartment_id": 2, "guest": "Bob"})
        self.assertEqual((r.json["apartment_id"], r.json["guest"]), (2, "Bob"))

    def test_change_into_other_booking_is_409(self):
        self.book(1, "2026-11-01", "2026-11-05")
        self.book(1, "2026-11-05", "2026-11-08")
        r = self.client.patch("/api/bookings/1", json={"check_out": "2026-11-06"})
        self.assertError(r, 409, "conflict", "booking 2")

    def test_cancel(self):
        self.book(1, "2026-11-01", "2026-11-05")
        r = self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertEqual((r.status_code, r.json["status"]), (200, "cancelled"))
        self.assertEqual(self.book(1, "2026-11-01", "2026-11-05").status_code, 201)

    def test_cancelled_booking_cannot_change_or_cancel_again(self):
        self.book(1, "2026-11-01", "2026-11-05")
        self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        r = self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertError(r, 409, "conflict", "already cancelled")
        r = self.client.patch("/api/bookings/1", json={"guest": "Bob"})
        self.assertError(r, 409, "conflict", "cannot be changed")

    def test_invalid_status_changes(self):
        self.book(1, "2026-11-01", "2026-11-05")
        r = self.client.patch("/api/bookings/1", json={"status": "active"})
        self.assertError(r, 400, "validation_error", "only be set to 'cancelled'")
        r = self.client.patch("/api/bookings/1", json={"status": "cancelled", "guest": "Bob"})
        self.assertError(r, 400, "validation_error", "cannot be combined")

    def test_unknown_booking_is_404(self):
        self.assertError(self.client.get("/api/bookings/9"), 404, "not_found", "Booking 9")
        r = self.client.patch("/api/bookings/9", json={"status": "cancelled"})
        self.assertError(r, 404, "not_found")


class MetaApiTests(ApiTestCase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual((r.status_code, r.json), (200, {"status": "ok"}))

    def test_openapi_spec_is_served(self):
        r = self.client.get("/api/openapi.yaml")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/yaml")
        self.assertIn(b"openapi: 3.0.3", r.data)


class PersistenceTests(unittest.TestCase):
    def test_data_survives_app_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            client = create_app(JsonStorage(path)).test_client()
            client.post("/api/apartments", json={"name": "Loft", "address": "x"})
            client.post("/api/bookings", json={
                "apartment_id": 1, "check_in": "2026-11-01", "check_out": "2026-11-05"})

            restarted = create_app(JsonStorage(path)).test_client()
            self.assertEqual(restarted.get("/api/apartments/1").json["name"], "Loft")
            self.assertEqual(restarted.get("/api/bookings/1").json["status"], "active")

    def test_default_data_file_comes_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "env.json")
            old = os.environ.get("APT_DATA_FILE")
            os.environ["APT_DATA_FILE"] = path
            try:
                create_app().test_client().post(
                    "/api/apartments", json={"name": "Loft", "address": "x"})
            finally:
                if old is None:
                    del os.environ["APT_DATA_FILE"]
                else:
                    os.environ["APT_DATA_FILE"] = old
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()

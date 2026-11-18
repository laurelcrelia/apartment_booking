import os
import tempfile
import unittest
from unittest import mock

from apartments_service.app import create_app
from apartments_service.repo import ApartmentRepo
from apartments_service.service import ApartmentService


class ApartmentsServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.client = create_app(ApartmentService(ApartmentRepo(":memory:"))).test_client()

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

    def test_knows_nothing_about_bookings(self):
        self.assertError(self.client.get("/api/bookings"), 404, "not_found")

    def test_health_and_json_http_errors(self):
        self.assertEqual(self.client.get("/api/health").json, {"status": "ok"})
        self.assertError(self.client.put("/api/apartments"), 405, "method_not_allowed")


class ConfigurationTests(unittest.TestCase):
    def test_database_comes_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "apts.db")
            with mock.patch.dict(os.environ, {"APARTMENTS_DB": path}):
                create_app().test_client().post("/api/apartments", json={"name": "Loft", "address": "x"})
            self.assertEqual(ApartmentRepo(path).get(1)["name"], "Loft")


if __name__ == "__main__":
    unittest.main()

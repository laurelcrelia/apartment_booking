import re
import unittest

import yaml
from openapi_spec_validator import validate

from apartment_booking.api import SPEC_PATH
from apartment_booking.storage import MemoryStorage
from apartment_booking.web import create_app

# HTML pages under /api that are deliberately not part of the JSON API.
UNDOCUMENTED = {"/api/docs"}


class OpenApiSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

    def test_spec_is_valid(self):
        validate(self.spec)

    def test_every_api_route_is_documented(self):
        app = create_app(MemoryStorage())
        prefix = self.spec["servers"][0]["url"]
        routes = set()
        for rule in app.url_map.iter_rules():
            if not rule.rule.startswith(prefix + "/") or rule.rule in UNDOCUMENTED:
                continue
            path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule[len(prefix):])
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                routes.add((path, method.lower()))
        documented = {
            (path, method)
            for path, item in self.spec["paths"].items()
            for method in item if method != "parameters"
        }
        self.assertEqual(routes, documented)


class PageTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(MemoryStorage()).test_client()
        self.client.post("/api/apartments", json={"name": "Loft <b>", "address": "1 Beach Rd"})
        self.client.post("/api/bookings", json={
            "apartment_id": 1, "check_in": "2026-11-01", "check_out": "2026-11-05", "guest": "Ann"})

    def get(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "text/html")
        return r.get_data(as_text=True)

    def test_apartments_page_lists_and_has_forms(self):
        html = self.get("/")
        self.assertIn("Loft &lt;b&gt;", html)  # escaped
        self.assertIn('data-api="/api/apartments" data-method="POST"', html)
        self.assertIn('data-api="/api/apartments" data-method="GET"', html)

    def test_apartment_page(self):
        html = self.get("/apartments/1?from=2026-12-01&to=2026-12-03")
        self.assertIn('data-method="PATCH"', html)
        self.assertIn('data-method="DELETE"', html)
        self.assertIn('value="2026-12-01"', html)  # booking form prefilled from search
        self.assertIn("Ann", html)

    def test_bookings_page_filters(self):
        self.assertIn("Ann", self.get("/bookings"))
        self.assertNotIn("Ann", self.get("/bookings?guest=Bob"))
        self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertNotIn("Ann", self.get("/bookings"))
        self.assertIn("Ann", self.get("/bookings?include_cancelled=true&apartment_id=1"))

    def test_booking_page(self):
        html = self.get("/bookings/1")
        self.assertIn('name="status" value="cancelled"', html)
        self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertIn("can no longer be changed", self.get("/bookings/1"))

    def test_api_docs_page(self):
        self.assertIn("/api/openapi.yaml", self.get("/api/docs"))

    def test_unknown_pages_are_404(self):
        for url in ("/apartments/9", "/bookings/9"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)


if __name__ == "__main__":
    unittest.main()

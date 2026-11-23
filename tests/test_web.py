import re
import unittest

import yaml
from openapi_spec_validator import validate

from bookings_service.api import SPEC_PATH
from werkzeug.test import Client

import devstack
from bookings_service.repos import BookingRepo
from bookings_service.service import BookingService
from devstack.gateway import FRONTEND_DIR, PAGES
from tests.helpers import Services
from bookings_service.app import create_app
from apartments_service.app import create_app as create_apartments_app

NGINX_CONF = FRONTEND_DIR.parent / "nginx" / "default.conf"


class OpenApiSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

    def test_spec_is_valid(self):
        validate(self.spec)

    def test_every_api_route_is_documented(self):
        # The public API is served by both services behind the gateway.
        services = Services()
        apps = [create_app(services.bookings), create_apartments_app(services.apartments)]
        prefix = self.spec["servers"][0]["url"]
        routes = set()
        for rule in (rule for app in apps for rule in app.url_map.iter_rules()):
            if not rule.rule.startswith(prefix + "/"):
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


class FrontendTests(unittest.TestCase):
    """The static frontend, as the gateway serves it (devstack/gateway.py)."""

    def setUp(self):
        stack = devstack.start()
        self.addCleanup(stack.stop)
        self.client = Client(stack.gateway)

    def get(self, path, status=200):
        r = self.client.get(path)
        self.assertEqual(r.status_code, status, path)
        return r

    def test_each_page_url_gets_its_html_file(self):
        for path, page in [("/", "index.html"), ("/apartments/12", "apartment.html"), ("/bookings", "bookings.html"),
                           ("/bookings/3", "booking.html"), ("/api/docs", "api-docs.html")]:
            with self.subTest(path=path):
                r = self.get(path)
                self.assertEqual(r.mimetype, "text/html")
                self.assertEqual(r.data, (FRONTEND_DIR / page).read_bytes())

    def test_pages_include_existing_scripts_and_styles(self):
        for page in FRONTEND_DIR.glob("*.html"):
            for url in re.findall(r'(?:src|href)="(/static/[^"]+)"', page.read_text()):
                with self.subTest(page=page.name, url=url):
                    self.get(url)

    def test_static_files(self):
        self.assertEqual(self.get("/static/app.js").mimetype, "text/javascript")
        self.assertEqual(self.get("/static/style.css").mimetype, "text/css")
        self.get("/static/missing.js", 404)
        self.get("/static/../bookings_service/service.py", 404)  # can't leave static/

    def test_unknown_paths_get_the_404_page(self):
        for path in ("/nope", "/apartments", "/apartments/abc", "/bookings/1/edit", "/index.html"):
            with self.subTest(path=path):
                self.assertIn(b"Page not found", self.get(path, 404).data)

    def test_api_still_goes_to_the_services(self):
        self.assertEqual(self.get("/api/bookings").json, [])
        self.assertEqual(self.get("/api/apartments").json, [])
        self.assertEqual(self.get("/api/nothing", 404).json["error"]["code"], "not_found")

    def test_web_app_serves_no_pages(self):
        client = create_app(BookingService(BookingRepo(":memory:"), apartments=None)).test_client()
        for path in ("/", "/bookings", "/static/app.js", "/api/docs"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_nginx_serves_the_same_pages(self):
        if not NGINX_CONF.exists():
            self.skipTest("nginx/ isn't in the Docker test image")
        nginx_pages = set(re.findall(r"try_files /([\w-]+\.html)", NGINX_CONF.read_text()))
        self.assertEqual(nginx_pages, {page for _, page in PAGES})


if __name__ == "__main__":
    unittest.main()

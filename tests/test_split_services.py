"""The booking app talking to a real apartments service over HTTP."""
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from flask import Flask
from werkzeug.serving import WSGIRequestHandler, make_server

from apartment_booking.apartments_client import HttpApartments
from apartment_booking.cli import main
from apartment_booking.service import open_service
from apartment_booking.web import create_app
from apartments_service.app import create_app as create_apartments_app
from apartments_service.repo import ApartmentRepo
from apartments_service.service import ApartmentService
from common.errors import BookingError, ConflictError, NotFoundError, ServiceUnavailableError


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def serve(test: unittest.TestCase, app) -> str:
    """Serve a WSGI app on a free port for the duration of the test; returns its URL."""
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}"


def closed_port_url() -> str:
    """A URL nothing listens on."""
    server = make_server("127.0.0.1", 0, Flask(__name__))
    port = server.server_port
    server.server_close()
    return f"http://127.0.0.1:{port}"


class SplitTestCase(unittest.TestCase):
    def setUp(self):
        self.apartments_url = serve(self, create_apartments_app(ApartmentService(ApartmentRepo(":memory:"))))


class HttpApartmentsTests(SplitTestCase):
    def setUp(self):
        super().setUp()
        self.apartments = HttpApartments(self.apartments_url + "/")

    def test_crud(self):
        a = self.apartments.add("Loft", "1 Beach Rd", rooms=2, price=80)
        self.assertEqual(a, {"id": 1, "name": "Loft", "address": "1 Beach Rd", "rooms": 2, "price": 80.0})
        self.assertEqual(self.apartments.get(1), a)
        self.assertEqual(self.apartments.list(), [a])
        self.assertEqual(self.apartments.update(1, price=95.5)["price"], 95.5)
        self.assertEqual(self.apartments.update(1)["price"], 95.5)
        self.assertIsNone(self.apartments.delete(1))
        self.assertEqual(self.apartments.list(), [])

    def test_errors_keep_their_type_and_message(self):
        with self.assertRaisesRegex(NotFoundError, "Apartment 9 not found"):
            self.apartments.get(9)
        with self.assertRaisesRegex(BookingError, "name is required") as ctx:
            self.apartments.add(" ", "x")
        self.assertNotIsInstance(ctx.exception, (NotFoundError, ConflictError, ServiceUnavailableError))

    def test_unreachable_service(self):
        with self.assertRaisesRegex(ServiceUnavailableError, "unavailable"):
            HttpApartments(closed_port_url()).list()

    def test_server_errors_and_bad_responses_mean_unavailable(self):
        broken = Flask(__name__)
        broken.get("/api/apartments", endpoint="e0")(lambda: ("<html>not json</html>", 200))
        broken.get("/api/apartments/<int:i>", endpoint="e1")(lambda i: ("oops", 500))
        broken.post("/api/apartments", endpoint="e2")(lambda: ({"error": {"code": "conflict", "message": "Taken"}}, 409))
        broken.delete("/api/apartments/<int:i>", endpoint="e3")(lambda i: ("<html>teapot</html>", 418))
        client = HttpApartments(serve(self, broken))
        with self.assertRaises(ServiceUnavailableError):
            client.list()
        with self.assertRaises(ServiceUnavailableError):
            client.get(1)
        with self.assertRaisesRegex(ConflictError, "Taken"):
            client.add("Loft", "x")
        with self.assertRaisesRegex(BookingError, "HTTP 418"):
            client.delete(1)


class GatewayTests(SplitTestCase):
    """The public API and pages of the booking app, with apartments served remotely."""

    def setUp(self):
        super().setUp()
        self.client = create_app(open_service(apartments_url=self.apartments_url)).test_client()

    def test_workflow_across_services(self):
        r = self.client.post("/api/apartments", json={"name": "Loft", "address": "x", "rooms": 2})
        self.assertEqual((r.status_code, r.headers["Location"]), (201, "/api/apartments/1"))
        self.assertEqual(HttpApartments(self.apartments_url).get(1)["name"], "Loft")
        r = self.client.post("/api/bookings", json={"apartment_id": 1, "check_in": "2026-11-01",
                                                    "check_out": "2026-11-05"})
        self.assertEqual(r.status_code, 201, r.json)
        r = self.client.get("/api/apartments?from=2026-11-02&to=2026-11-03")
        self.assertEqual(r.json, [])
        r = self.client.delete("/api/apartments/1")
        self.assertEqual((r.status_code, r.json["error"]["code"]), (409, "conflict"))
        self.client.patch("/api/bookings/1", json={"status": "cancelled"})
        self.assertEqual(self.client.delete("/api/apartments/1").status_code, 204)
        with self.assertRaises(NotFoundError):
            HttpApartments(self.apartments_url).get(1)

    def test_remote_validation_errors_pass_through(self):
        r = self.client.post("/api/apartments", json={"name": " ", "address": "x"})
        self.assertEqual((r.status_code, r.json["error"]["code"]), (400, "validation_error"))
        self.assertIn("name is required", r.json["error"]["message"])
        r = self.client.post("/api/bookings", json={"apartment_id": 7, "check_in": "2026-11-01",
                                                    "check_out": "2026-11-05"})
        self.assertEqual((r.status_code, r.json["error"]["message"]), (404, "Apartment 7 not found"))


class ApartmentsDownTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(open_service(apartments_url=closed_port_url())).test_client()

    def test_api_answers_503(self):
        for method, path, body in [
            ("get", "/api/apartments", None),
            ("get", "/api/apartments/1", None),
            ("post", "/api/apartments", {"name": "Loft", "address": "x"}),
            ("post", "/api/bookings", {"apartment_id": 1, "check_in": "2026-11-01", "check_out": "2026-11-05"}),
        ]:
            with self.subTest(path=path, method=method):
                r = getattr(self.client, method)(path, json=body)
                self.assertEqual(r.status_code, 503, r.json)
                self.assertEqual(r.json["error"]["code"], "service_unavailable")

    def test_bookings_without_apartments_still_work(self):
        r = self.client.get("/api/bookings")
        self.assertEqual((r.status_code, r.json), (200, []))

    def test_pages_answer_503(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 503)
        self.assertIn(b"The apartments service is unavailable", r.data)


class CliTests(SplitTestCase):
    def test_cli_uses_apartments_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                main(["apartment", "add", "--name", "Loft", "--address", "x",
                      "--apartments-url", self.apartments_url,
                      "--bookings-db", os.path.join(tmp, "bookings.db")])
                code = main(["apartment", "remove", "1", "--apartments-url", self.apartments_url,
                             "--bookings-db", os.path.join(tmp, "bookings.db")])
            self.assertEqual(code, 0, err.getvalue())
            self.assertIn("Removed apartment: [1] Loft", out.getvalue())
            # No local apartments database was used.
            self.assertFalse(os.path.exists(os.path.join(tmp, "apartments.db")))


if __name__ == "__main__":
    unittest.main()

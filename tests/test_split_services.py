"""The two services talking to each other over HTTP, as deployed."""
import threading
import unittest
from functools import partial

from flask import Flask
from werkzeug.serving import WSGIRequestHandler, make_server
from werkzeug.test import Client

from bookings_service.apartments_client import HttpApartments
from bookings_service.service import open_service
from bookings_service.app import create_app
from apartments_service.app import create_app as create_apartments_app
from apartments_service.bookings_client import HttpBookings
from apartments_service.consumer import handle_booking_event
from apartments_service.repo import ApartmentRepo
from apartments_service.service import ApartmentService
from common.errors import BookingError, ConflictError, NotFoundError, ServiceUnavailableError
from common.client import ServiceClient
from common.relay import Relay
from devstack import LocalPublisher
from devstack.gateway import Gateway


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
    """Both services on their own ports, each calling the other over HTTP, plus
    the stand-in gateway over them for the public API."""

    def setUp(self):
        web = {}  # the web app needs the apartments URL, and the other way round
        self.web_url = serve(self, lambda environ, start: web["app"](environ, start))
        self.apartments_repo = ApartmentRepo(":memory:")
        apartments_app = create_apartments_app(ApartmentService(self.apartments_repo, HttpBookings(self.web_url)))
        self.apartments_url = serve(self, apartments_app)
        self.service = open_service(":memory:", self.apartments_url)
        web["app"] = create_app(self.service)
        self.client = Client(Gateway(web["app"], apartments_app))

    def deliver_booking_events(self):
        """What the booking worker does through RabbitMQ in Docker."""
        Relay(self.service.bookings.outbox,
              LocalPublisher(partial(handle_booking_event, self.apartments_repo))).publish_pending()


class HttpApartmentsTests(SplitTestCase):
    def test_get(self):
        self.client.post("/api/apartments", json={"name": "Loft", "address": "1 Beach Rd", "rooms": 2, "price": 80})
        self.assertEqual(HttpApartments(self.apartments_url + "/").get(1),
                         {"id": 1, "name": "Loft", "address": "1 Beach Rd", "rooms": 2, "price": 80.0})

    def test_errors_keep_their_type_and_message(self):
        with self.assertRaisesRegex(NotFoundError, "Apartment 9 not found"):
            HttpApartments(self.apartments_url).get(9)
        with self.assertRaisesRegex(BookingError, "name is required") as ctx:
            ServiceClient(self.apartments_url).call("POST", "/api/apartments", {"name": " ", "address": "x"})
        self.assertNotIsInstance(ctx.exception, (NotFoundError, ConflictError, ServiceUnavailableError))

    def test_unreachable_service(self):
        with self.assertRaisesRegex(ServiceUnavailableError, "apartments service is unavailable"):
            HttpApartments(closed_port_url()).get(1)

    def test_server_errors_and_bad_responses_mean_unavailable(self):
        broken = Flask(__name__)
        broken.get("/api/apartments", endpoint="e0")(lambda: ("<html>not json</html>", 200))
        broken.get("/api/apartments/<int:i>", endpoint="e1")(lambda i: ("oops", 500))
        broken.post("/api/apartments", endpoint="e2")(lambda: ({"error": {"code": "conflict", "message": "Taken"}}, 409))
        broken.delete("/api/apartments/<int:i>", endpoint="e3")(lambda i: ("<html>teapot</html>", 418))
        client = HttpApartments(serve(self, broken))
        with self.assertRaises(ServiceUnavailableError):
            client.call("GET", "/api/apartments")
        with self.assertRaises(ServiceUnavailableError):
            client.get(1)
        with self.assertRaisesRegex(ConflictError, "Taken"):
            client.call("POST", "/api/apartments", {})
        with self.assertRaisesRegex(BookingError, "HTTP 418"):
            client.call("DELETE", "/api/apartments/1")


class GatewayTests(SplitTestCase):
    """The public API through the gateway, with the services calling each other over HTTP."""

    def test_workflow_across_services(self):
        r = self.client.post("/api/apartments", json={"name": "Loft", "address": "x", "rooms": 2})
        self.assertEqual((r.status_code, r.headers["Location"]), (201, "/api/apartments/1"))
        self.assertEqual(HttpApartments(self.apartments_url).get(1)["name"], "Loft")
        r = self.client.post("/api/bookings", json={"apartment_id": 1, "check_in": "2026-11-01",
                                                    "check_out": "2026-11-05"})
        self.assertEqual(r.status_code, 201, r.json)
        # The delete check asks the booking service over HTTP: strict right away.
        r = self.client.delete("/api/apartments/1")
        self.assertEqual((r.status_code, r.json["error"]["code"]), (409, "conflict"))
        # Search reads the apartments service's replica, once the event arrives.
        self.assertEqual([a["id"] for a in self.client.get("/api/apartments?from=2026-11-02&to=2026-11-03").json], [1])
        self.deliver_booking_events()
        self.assertEqual(self.client.get("/api/apartments?from=2026-11-02&to=2026-11-03").json, [])
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
    """The booking service while the apartments service is unreachable.

    (/api/apartments itself then gets its 503 from the gateway.)"""

    def setUp(self):
        self.client = create_app(open_service(":memory:", closed_port_url())).test_client()

    def test_booking_an_unknown_apartment_answers_503(self):
        r = self.client.post("/api/bookings", json={"apartment_id": 1, "check_in": "2026-11-01",
                                                    "check_out": "2026-11-05"})
        self.assertEqual(r.status_code, 503, r.json)
        self.assertEqual(r.json["error"]["code"], "service_unavailable")

    def test_bookings_without_apartments_still_work(self):
        r = self.client.get("/api/bookings")
        self.assertEqual((r.status_code, r.json), (200, []))


class BookingsDownTests(unittest.TestCase):
    """The apartments service while the booking service is unreachable."""

    def setUp(self):
        service = ApartmentService(ApartmentRepo(":memory:"), HttpBookings(closed_port_url()))
        self.client = create_apartments_app(service).test_client()
        self.client.post("/api/apartments", json={"name": "Loft", "address": "x"})

    def test_delete_answers_503_and_keeps_the_apartment(self):
        r = self.client.delete("/api/apartments/1")
        self.assertEqual((r.status_code, r.json["error"]["code"]), (503, "service_unavailable"))
        self.assertIn("booking service is unavailable", r.json["error"]["message"])
        self.assertEqual(self.client.get("/api/apartments/1").status_code, 200)

    def test_reads_and_search_keep_working(self):
        self.assertEqual(len(self.client.get("/api/apartments").json), 1)
        self.assertEqual(len(self.client.get("/api/apartments?from=2026-11-01&to=2026-11-02").json), 1)


if __name__ == "__main__":
    unittest.main()

"""Shared helpers for the black-box HTTP API tests.

The tests only talk to the app over HTTP, so the same suite can check the
monolith today and the split services later without changing a test body.

Target:
  API_BASE_URL=http://localhost:8000   test a running app (e.g. docker compose)
  (unset)                              start the app in-process on a free port

Only start_local_server() knows how the app is built; adapt it, not the tests,
when the internals change.
"""
from __future__ import annotations

import atexit
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlencode, urlparse

# Far in the future, so tests never collide with real bookings in a shared database.
YEAR = 2098

_base_url: str | None = None


def start_local_server() -> str:
    """Start the apartments service and the booking web app on free ports,
    talking to each other over HTTP like the deployed services, plus a relay
    thread that delivers apartment events to the booking side a little later,
    as RabbitMQ would; returns the web app's URL."""
    from werkzeug.serving import WSGIRequestHandler, make_server

    from apartment_booking.inprocess import LocalPublisher
    from apartment_booking.repos import BookingRepo
    from apartment_booking.service import open_service
    from apartment_booking.web import create_app
    from apartments_service.app import create_app as create_apartments_app
    from apartments_service.relay import Relay
    from apartments_service.repo import ApartmentRepo
    from apartments_service.service import ApartmentService

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, *args):
            pass

    def serve(app):
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    tmp = tempfile.TemporaryDirectory()
    servers = []
    apartments_repo = ApartmentRepo(os.path.join(tmp.name, "apartments.db"))
    bookings_db = os.path.join(tmp.name, "bookings.db")
    apartments_url = serve(create_apartments_app(ApartmentService(apartments_repo)))
    web_url = serve(create_app(open_service(bookings_db=bookings_db, apartments_url=apartments_url)))

    relay = Relay(apartments_repo.outbox, LocalPublisher(BookingRepo(bookings_db)))
    stopping = threading.Event()

    def deliver_events():
        while not stopping.wait(0.2):
            relay.publish_pending()
    relay_thread = threading.Thread(target=deliver_events, daemon=True)
    relay_thread.start()

    def stop():
        stopping.set()
        relay_thread.join()
        for server in servers:
            server.shutdown()
        tmp.cleanup()
    atexit.register(stop)
    return web_url


def base_url() -> str:
    global _base_url
    if _base_url is None:
        _base_url = (os.environ.get("API_BASE_URL") or start_local_server()).rstrip("/")
    return _base_url


class Response:
    def __init__(self, status: int, headers, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    @property
    def json(self):
        return json.loads(self.body) if self.body else None

    @property
    def content_type(self) -> str:
        return (self.headers.get("Content-Type") or "").split(";")[0].strip()


def request(method: str, path: str, json_body=None, data: bytes | None = None,
            content_type: str | None = None, query: dict | None = None) -> Response:
    url = base_url() + path
    if query:
        url += "?" + urlencode(query)
    if json_body is not None:
        data, content_type = json.dumps(json_body).encode(), "application/json"
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return Response(res.status, res.headers, res.read())
    except urllib.error.HTTPError as e:
        with e:
            return Response(e.code, e.headers, e.read())


def unique(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def day(month: int, d: int) -> str:
    return f"{YEAR}-{month:02d}-{d:02d}"


def eventually(check, timeout: float = 10.0, interval: float = 0.1):
    """Retry `check` until it stops raising AssertionError.

    For reads that may become eventually consistent once services exchange
    events. Against the monolith the first attempt already passes.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            return check()
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval)


class ApiTestCase(unittest.TestCase):
    """Creates its own data with unique names and removes it afterwards.

    Never assumes an empty database or particular IDs.
    """

    get = staticmethod(lambda path, **kw: request("GET", path, **kw))
    post = staticmethod(lambda path, body=None, **kw: request("POST", path, json_body=body, **kw))
    patch = staticmethod(lambda path, body=None, **kw: request("PATCH", path, json_body=body, **kw))
    delete = staticmethod(lambda path, **kw: request("DELETE", path, **kw))

    def add_apartment(self, **fields) -> dict:
        body = {"name": unique("Loft"), "address": "1 Test St", **fields}
        r = self.post("/api/apartments", body)
        self.assertEqual(r.status, 201, r.body)
        self.addCleanup(self._remove_apartment, r.json["id"])
        return r.json

    def book(self, apartment_id, check_in, check_out, guest="Ann") -> Response:
        return self.post("/api/bookings", {"apartment_id": apartment_id, "guest": guest,
                                           "check_in": check_in, "check_out": check_out})

    def booked(self, apartment_id, check_in, check_out, guest="Ann") -> dict:
        r = self.book(apartment_id, check_in, check_out, guest)
        self.assertEqual(r.status, 201, r.body)
        return r.json

    def search(self, **query) -> list[int]:
        r = self.get("/api/apartments", query=query)
        self.assertEqual(r.status, 200, r.body)
        return [a["id"] for a in r.json]

    def _remove_apartment(self, apartment_id):
        active = self.get("/api/bookings", query={"apartment_id": apartment_id}).json or []
        for b in active:
            self.patch(f"/api/bookings/{b['id']}", {"status": "cancelled"})
        self.delete(f"/api/apartments/{apartment_id}")

    # ---------- assertions ----------

    def assertError(self, r: Response, status: int, code: str, message_part: str = ""):
        self.assertEqual(r.status, status, r.body)
        self.assertEqual(r.content_type, "application/json", r.body)
        self.assertEqual(r.json["error"]["code"], code)
        self.assertIn(message_part, r.json["error"]["message"])

    def assertLocation(self, r: Response, path: str):
        self.assertEqual(urlparse(r.headers["Location"]).path, path)

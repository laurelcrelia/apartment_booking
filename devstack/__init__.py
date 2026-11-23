"""The whole app without Docker: both services, the gateway and event delivery in one process.

    python -m devstack [--port 8000]

It runs the same code as Docker Compose, minus NGINX and RabbitMQ:

- the apartments and booking services each run as their own HTTP server on a
  free port and call each other over HTTP, as in Docker;
- a Python stand-in for NGINX (gateway.py) serves the frontend and routes /api
  by path, with the same routes as nginx/default.conf;
- events go from each service's outbox straight to the other service's
  handler instead of through RabbitMQ: right after every change made through
  the gateway (sync_events=True, the default, so both replicas are always
  current), or a little later from a background thread (sync_events=False,
  like RabbitMQ; the black-box API tests use that).

Used for local development and by the tests.
"""
from __future__ import annotations

import threading
from functools import partial

from werkzeug.serving import WSGIRequestHandler, make_server

from apartments_service.app import create_app as create_apartments_app
from apartments_service.bookings_client import HttpBookings
from apartments_service.consumer import handle_booking_event
from apartments_service.repo import ApartmentRepo
from apartments_service.service import ApartmentService
from bookings_service.apartments_client import HttpApartments
from bookings_service.consumer import handle_event
from bookings_service.repos import BookingRepo
from bookings_service.service import BookingService
from bookings_service.app import create_app as create_bookings_app
from common.client import ServiceClient
from common.events import decode, encode
from common.relay import Relay

from .gateway import Gateway


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args):
        pass


class LocalPublisher:
    """A relay publisher that hands each event straight to handler(event)."""

    def __init__(self, handler):
        self.handler = handler

    def publish(self, event: dict) -> None:
        # Through JSON, like a real message, so nothing non-serializable slips through.
        self.handler(decode(encode(event)))


class Stack:
    """A running stack. url is the gateway; call() sends a request to the API through it."""

    def __init__(self):
        self._servers = []
        self._stopping = threading.Event()
        self._threads = []

    def serve(self, app, host: str, port: int = 0) -> str:
        server = make_server(host, port, app, threaded=True, request_handler=QuietHandler)
        # A short poll interval makes stop() quick (tests start a stack each).
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self._servers.append(server)
        return f"http://{host}:{server.server_port}"

    def deliver_events(self) -> None:
        """Deliver every pending event in both directions."""
        for relay in self.relays:
            relay.publish_pending()

    def deliver_events_every(self, seconds: float) -> None:
        def loop():
            while not self._stopping.wait(seconds):
                self.deliver_events()
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self._threads.append(thread)

    def call(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        """JSON from the public API; errors raise the usual exceptions (see common.client)."""
        return ServiceClient(self.url, timeout=10).call(method, path, body, query)

    def stop(self) -> None:
        self._stopping.set()
        for thread in self._threads:
            thread.join()
        for server in self._servers:
            server.shutdown()
            server.server_close()


def start(apartments_db: str = ":memory:", bookings_db: str = ":memory:", *,
          host: str = "127.0.0.1", port: int = 0, sync_events: bool = True,
          event_delay: float = 0.2) -> Stack:
    """Start the stack; the defaults keep all data in memory on a free port."""
    stack = Stack()
    apartments_repo, bookings_repo = ApartmentRepo(apartments_db), BookingRepo(bookings_db)
    # Each service needs the other's URL, so their servers start with a stand-in app.
    apps = {}
    stack.bookings_url = stack.serve(lambda environ, start: apps["bookings"](environ, start), host)
    stack.apartments_url = stack.serve(lambda environ, start: apps["apartments"](environ, start), host)
    apps["apartments"] = create_apartments_app(ApartmentService(apartments_repo, HttpBookings(stack.bookings_url)))
    apps["bookings"] = create_bookings_app(BookingService(bookings_repo, HttpApartments(stack.apartments_url)))
    stack.relays = [
        Relay(apartments_repo.outbox, LocalPublisher(partial(handle_event, bookings_repo))),
        Relay(bookings_repo.outbox, LocalPublisher(partial(handle_booking_event, apartments_repo))),
    ]
    stack.deliver_events()  # data that existed before events did
    stack.gateway = Gateway(apps["bookings"], apps["apartments"],
                            after_write=stack.deliver_events if sync_events else None)
    if not sync_events:
        stack.deliver_events_every(event_delay)
    stack.url = stack.serve(stack.gateway, host, port)
    return stack

"""Command-line interface: a client of the public REST API, through the gateway.

It needs the app to be running (e.g. `docker compose up`), and works on the
same data as the web pages.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from common.client import ServiceClient
from common.errors import BookingError

DEFAULT_API = "http://localhost:8000"

PROG = "booking.py"

HELP = f"""\
Usage: {PROG} COMMAND [OPTIONS]
Commands:
apartment list
apartment view ID
apartment add --name NAME --address ADDRESS [--rooms N] [--price PRICE]
apartment update ID [--name NAME] [--address ADDRESS] [--rooms N] [--price PRICE]
apartment remove ID
apartment search --from DATE --to DATE [--min-rooms N]
booking list [--apartment ID] [--guest NAME] [--all]
booking view ID
booking create --apartment ID --from DATE --to DATE [--guest NAME]
booking change ID [--from DATE] [--to DATE] [--apartment ID] [--guest NAME]
booking cancel ID
Options (any command):
--json       print results as JSON
--api URL    the app to talk to (default: $API_URL or {DEFAULT_API})
Dates are YYYY-MM-DD; --to is the check-out day (exclusive).
"""


class _HelpAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS)

    def __call__(self, parser, namespace, values, option_string=None):
        print(HELP, end="")
        parser.exit()


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api", default=os.environ.get("API_URL", DEFAULT_API))
    common.add_argument("--json", action="store_true")

    p = argparse.ArgumentParser(prog=PROG, add_help=False)
    p.add_argument("-h", "--help", action=_HelpAction)
    groups = p.add_subparsers(dest="group", metavar="COMMAND")
    groups.required = True

    def command(subparsers, name):
        return subparsers.add_parser(name, parents=[common])

    apt = groups.add_parser("apartment").add_subparsers(dest="cmd", metavar="COMMAND")
    apt.required = True
    command(apt, "list")
    a = command(apt, "view")
    a.add_argument("id", type=int)
    a = command(apt, "add")
    a.add_argument("--name", required=True)
    a.add_argument("--address", required=True)
    a.add_argument("--rooms", type=int, default=1)
    a.add_argument("--price", type=float, default=0.0, help="price per night")
    a = command(apt, "update")
    a.add_argument("id", type=int)
    a.add_argument("--name")
    a.add_argument("--address")
    a.add_argument("--rooms", type=int)
    a.add_argument("--price", type=float)
    a = command(apt, "remove")
    a.add_argument("id", type=int)
    a = command(apt, "search")
    a.add_argument("--from", dest="check_in", metavar="DATE", required=True)
    a.add_argument("--to", dest="check_out", metavar="DATE", required=True)
    a.add_argument("--min-rooms", type=int, default=1)

    bk = groups.add_parser("booking").add_subparsers(dest="cmd", metavar="COMMAND")
    bk.required = True
    b = command(bk, "list")
    b.add_argument("--apartment", type=int)
    b.add_argument("--guest")
    b.add_argument("--all", action="store_true", help="include cancelled bookings")
    b = command(bk, "view")
    b.add_argument("id", type=int)
    b = command(bk, "create")
    b.add_argument("--apartment", type=int, metavar="ID", required=True)
    b.add_argument("--from", dest="check_in", metavar="DATE", required=True)
    b.add_argument("--to", dest="check_out", metavar="DATE", required=True)
    b.add_argument("--guest", default="")
    b = command(bk, "change")
    b.add_argument("id", type=int)
    b.add_argument("--from", dest="check_in", metavar="DATE")
    b.add_argument("--to", dest="check_out", metavar="DATE")
    b.add_argument("--apartment", type=int, metavar="ID")
    b.add_argument("--guest")
    b = command(bk, "cancel")
    b.add_argument("id", type=int)
    return p


def fmt_apartment(a: dict) -> str:
    return f"[{a['id']}] {a['name']} | {a['address'] or '-'} | rooms: {a['rooms']} | {a['price']:.2f}/night"


def fmt_booking(b: dict) -> str:
    return (f"[{b['id']}] apartment {b['apartment_id']} | {b['guest'] or '-'} | "
            f"{b['check_in']} -> {b['check_out']} | {b['status']}")


class Api(ServiceClient):
    """The public REST API; its error messages are shown as they are."""

    @property
    def unavailable(self) -> str:
        return f"Can't reach the app at {self.base_url}; is it running?"


def _given(**fields) -> dict:
    return {k: v for k, v in fields.items() if v is not None}


def run(args, api: Api):
    """Dispatch a parsed command. Returns (message, result) where result is a dict/list."""
    if args.group == "apartment":
        path = f"/api/apartments/{getattr(args, 'id', '')}"
        if args.cmd == "list":
            return "No apartments", api.call("GET", "/api/apartments")
        if args.cmd == "view":
            return None, api.call("GET", path)
        if args.cmd == "add":
            body = {"name": args.name, "address": args.address, "rooms": args.rooms, "price": args.price}
            return "Added apartment", api.call("POST", "/api/apartments", body)
        if args.cmd == "update":
            body = _given(name=args.name, address=args.address, rooms=args.rooms, price=args.price)
            return "Updated apartment", api.call("PATCH", path, body)
        if args.cmd == "remove":
            apartment = api.call("GET", path)
            api.call("DELETE", path)
            return "Removed apartment", apartment
        if args.cmd == "search":
            query = {"from": args.check_in, "to": args.check_out, "min_rooms": args.min_rooms}
            return "No apartments available", api.call("GET", "/api/apartments", query=query)
    elif args.group == "booking":
        path = f"/api/bookings/{getattr(args, 'id', '')}"
        if args.cmd == "list":
            query = _given(apartment_id=args.apartment, guest=args.guest)
            if args.all:
                query["include_cancelled"] = "true"
            return "No bookings", api.call("GET", "/api/bookings", query=query)
        if args.cmd == "view":
            return None, api.call("GET", path)
        if args.cmd == "create":
            body = {"apartment_id": args.apartment, "guest": args.guest,
                    "check_in": args.check_in, "check_out": args.check_out}
            return "Created booking", api.call("POST", "/api/bookings", body)
        if args.cmd == "change":
            body = _given(apartment_id=args.apartment, guest=args.guest,
                          check_in=args.check_in, check_out=args.check_out)
            return "Changed booking", api.call("PATCH", path, body)
        if args.cmd == "cancel":
            return "Cancelled booking", api.call("PATCH", path, {"status": "cancelled"})
    raise BookingError("Unknown command")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(HELP, end="")
        return 0
    args = build_parser().parse_args(argv)
    try:
        message, result = run(args, Api(args.api, timeout=10))
    except BookingError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    fmt = fmt_booking if args.group == "booking" else fmt_apartment
    if isinstance(result, list):
        if not result:
            print(message)
        for item in result:
            print(fmt(item))
    else:
        print(f"{message}: {fmt(result)}" if message else fmt(result))
    return 0

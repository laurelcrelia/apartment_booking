"""Command-line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .service import BookingError, BookingService
from .storage import JsonStorage

DEFAULT_DATA_FILE = os.environ.get("APT_DATA_FILE", "data.json")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="apt", description="Apartment booking CLI")
    p.add_argument("--data", default=DEFAULT_DATA_FILE,
                   help="path to JSON data file (default: $APT_DATA_FILE or ./data.json)")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    sub = p.add_subparsers(dest="group", required=True)

    # apartment
    apt = sub.add_parser("apartment", help="manage apartments").add_subparsers(dest="cmd", required=True)
    a = apt.add_parser("add", help="add an apartment")
    a.add_argument("name")
    a.add_argument("--address", default="")
    a.add_argument("--rooms", type=int, default=1)
    a.add_argument("--price", type=float, default=0.0, help="price per night")
    a = apt.add_parser("update", help="update an apartment")
    a.add_argument("id", type=int)
    a.add_argument("--name")
    a.add_argument("--address")
    a.add_argument("--rooms", type=int)
    a.add_argument("--price", type=float)
    a = apt.add_parser("remove", help="remove an apartment")
    a.add_argument("id", type=int)
    a = apt.add_parser("view", help="view one apartment")
    a.add_argument("id", type=int)
    apt.add_parser("list", help="list all apartments")

    # booking
    bk = sub.add_parser("booking", help="manage bookings").add_subparsers(dest="cmd", required=True)
    b = bk.add_parser("create", help="create a booking")
    b.add_argument("apartment_id", type=int)
    b.add_argument("guest")
    b.add_argument("check_in", help="YYYY-MM-DD")
    b.add_argument("check_out", help="YYYY-MM-DD (exclusive)")
    b = bk.add_parser("view", help="view one booking")
    b.add_argument("id", type=int)
    b = bk.add_parser("list", help="list bookings")
    b.add_argument("--apartment", type=int)
    b.add_argument("--guest")
    b.add_argument("--all", action="store_true", help="include cancelled bookings")
    b = bk.add_parser("change", help="change a booking")
    b.add_argument("id", type=int)
    b.add_argument("--apartment", type=int)
    b.add_argument("--guest")
    b.add_argument("--check-in")
    b.add_argument("--check-out")
    b = bk.add_parser("cancel", help="cancel a booking")
    b.add_argument("id", type=int)

    # search
    s = sub.add_parser("search", help="find apartments available for a date range")
    s.add_argument("check_in", help="YYYY-MM-DD")
    s.add_argument("check_out", help="YYYY-MM-DD (exclusive)")
    s.add_argument("--min-rooms", type=int, default=1)
    return p


def fmt_apartment(a: dict) -> str:
    return f"[{a['id']}] {a['name']} | {a['address'] or '-'} | rooms: {a['rooms']} | {a['price']:.2f}/night"


def fmt_booking(b: dict) -> str:
    return (f"[{b['id']}] apartment {b['apartment_id']} | {b['guest']} | "
            f"{b['check_in']} -> {b['check_out']} | {b['status']}")


def run(args, svc: BookingService):
    """Dispatch a parsed command. Returns (message, result) where result is a dict/list."""
    if args.group == "apartment":
        if args.cmd == "add":
            r = svc.add_apartment(args.name, args.address, args.rooms, args.price)
            return "Added apartment", r
        if args.cmd == "update":
            r = svc.update_apartment(args.id, args.name, args.address, args.rooms, args.price)
            return "Updated apartment", r
        if args.cmd == "remove":
            return "Removed apartment", svc.remove_apartment(args.id)
        if args.cmd == "view":
            return None, svc.get_apartment(args.id)
        if args.cmd == "list":
            return "No apartments", svc.list_apartments()
    elif args.group == "booking":
        if args.cmd == "create":
            r = svc.create_booking(args.apartment_id, args.guest, args.check_in, args.check_out)
            return "Created booking", r
        if args.cmd == "view":
            return None, svc.get_booking(args.id)
        if args.cmd == "list":
            return "No bookings", svc.list_bookings(args.apartment, args.guest, args.all)
        if args.cmd == "change":
            r = svc.change_booking(args.id, args.apartment, args.guest, args.check_in, args.check_out)
            return "Changed booking", r
        if args.cmd == "cancel":
            return "Cancelled booking", svc.cancel_booking(args.id)
    elif args.group == "search":
        return "No apartments available", svc.search_available(args.check_in, args.check_out, args.min_rooms)
    raise BookingError("Unknown command")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    svc = BookingService(JsonStorage(args.data))
    try:
        message, result = run(args, svc)
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

"""Command-line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .service import BookingError, BookingService
from .storage import JsonStorage

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
--json         print results as JSON
--data PATH    data file (default: $APT_DATA_FILE or ./data.json)
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
    common.add_argument("--data", default=os.environ.get("APT_DATA_FILE", "data.json"))
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


def run(args, svc: BookingService):
    """Dispatch a parsed command. Returns (message, result) where result is a dict/list."""
    if args.group == "apartment":
        if args.cmd == "list":
            return "No apartments", svc.list_apartments()
        if args.cmd == "view":
            return None, svc.get_apartment(args.id)
        if args.cmd == "add":
            r = svc.add_apartment(args.name, args.address, args.rooms, args.price)
            return "Added apartment", r
        if args.cmd == "update":
            r = svc.update_apartment(args.id, args.name, args.address, args.rooms, args.price)
            return "Updated apartment", r
        if args.cmd == "remove":
            return "Removed apartment", svc.remove_apartment(args.id)
        if args.cmd == "search":
            return "No apartments available", svc.search_available(
                args.check_in, args.check_out, args.min_rooms)
    elif args.group == "booking":
        if args.cmd == "list":
            return "No bookings", svc.list_bookings(args.apartment, args.guest, args.all)
        if args.cmd == "view":
            return None, svc.get_booking(args.id)
        if args.cmd == "create":
            r = svc.create_booking(args.apartment, args.guest, args.check_in, args.check_out)
            return "Created booking", r
        if args.cmd == "change":
            r = svc.change_booking(args.id, args.apartment, args.guest, args.check_in, args.check_out)
            return "Changed booking", r
        if args.cmd == "cancel":
            return "Cancelled booking", svc.cancel_booking(args.id)
    raise BookingError("Unknown command")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(HELP, end="")
        return 0
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

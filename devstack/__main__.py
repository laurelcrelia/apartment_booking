"""python -m devstack [--port 8000]: run the whole app locally, without Docker."""
import argparse
import os
import threading

from . import start

p = argparse.ArgumentParser(prog="python -m devstack", description="Run the whole app locally, without Docker.")
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", type=int, default=8000)
args = p.parse_args()
stack = start(os.environ.get("APARTMENTS_DB", "apartments.db"), os.environ.get("BOOKINGS_DB", "bookings.db"),
              host=args.host, port=args.port)
print(f"Apartment Booking on {stack.url}  (apartments service {stack.apartments_url}, "
      f"booking service {stack.bookings_url}); Ctrl+C to stop")
try:
    threading.Event().wait()
except KeyboardInterrupt:
    stack.stop()

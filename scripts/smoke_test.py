#!/usr/bin/env python3
"""End-to-end check of a running app: drives every workflow through the REST API
and loads every page. Uses only the standard library.

    python3 scripts/smoke_test.py [BASE_URL] [--keep]

BASE_URL defaults to http://localhost:8000. The script removes what it created
unless --keep is given; then it prints the ID of an apartment it left behind,
so you can check it is still there after a restart.
"""
import json
import sys
import urllib.error
import urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = (args[0] if args else "http://localhost:8000").rstrip("/")
KEEP = "--keep" in sys.argv


def call(method, path, body=None, expect=200):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            status, raw = res.status, res.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    if status != expect:
        sys.exit(f"FAIL {method} {path}: expected {expect}, got {status}: {raw[:300]!r}")
    print(f"ok   {method:6} {path} -> {status}")
    is_json = raw[:1] in (b"{", b"[")
    return json.loads(raw) if is_json else raw


call("GET", "/api/health")

# Apartments
loft = call("POST", "/api/apartments",
            {"name": "Smoke Loft", "address": "1 Test St", "rooms": 2, "price": 80}, expect=201)
studio = call("POST", "/api/apartments", {"name": "Smoke Studio", "address": "2 Test St"}, expect=201)
call("GET", f"/api/apartments/{loft['id']}")
call("PATCH", f"/api/apartments/{loft['id']}", {"price": 90})
assert any(a["id"] == loft["id"] for a in call("GET", "/api/apartments"))

# Bookings, search and the overlap rule
stay = {"check_in": "2099-11-01", "check_out": "2099-11-05"}
booking = call("POST", "/api/bookings", {"apartment_id": loft["id"], "guest": "Ann", **stay}, expect=201)
call("POST", "/api/bookings", {"apartment_id": loft["id"], "check_in": "2099-11-04",
                               "check_out": "2099-11-06"}, expect=409)
free = call("GET", "/api/apartments?from=2099-11-02&to=2099-11-03")
assert loft["id"] not in [a["id"] for a in free], "booked apartment shown as available"
call("PATCH", f"/api/bookings/{booking['id']}", {"check_out": "2099-11-06", "guest": "Ann B"})
call("GET", f"/api/bookings?apartment_id={loft['id']}")
call("DELETE", f"/api/apartments/{loft['id']}", expect=409)

# Pages and static files
for page in ("/", "/bookings", f"/apartments/{loft['id']}", f"/bookings/{booking['id']}",
             "/api/docs", "/api/openapi.yaml", "/static/app.js", "/static/style.css"):
    call("GET", page)

# Clean up: cancelling frees the apartment so it can be removed
call("PATCH", f"/api/bookings/{booking['id']}", {"status": "cancelled"})
call("DELETE", f"/api/apartments/{studio['id']}", expect=204)
if KEEP:
    print(f"kept apartment {loft['id']}")
    print(f"KEPT_APARTMENT_ID={loft['id']}")
else:
    call("DELETE", f"/api/apartments/{loft['id']}", expect=204)
print("All smoke checks passed")

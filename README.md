# Apartment Booking

Authors: Laurel Matt and Kleidi Gjeta

> This app was made as an exercise for the course Continuous Integration and Delivery (76106B) at the Free University of Bozen-Bolzano (unibz).

Web app for managing apartments and bookings, with availability search and overlap prevention. It has web pages for every workflow, a REST API documented with OpenAPI, and a command-line interface, all working on the same data.

## Quick start

You need Docker with Compose v2; no local Python is needed.

```sh
git clone https://github.com/laurelcrelia/apartment_booking.git
cd apartment_booking
printf 'RABBITMQ_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env   # once: your local secrets
docker compose up -d --build --wait
```

Then open **<http://localhost:8000>**.

| To… | Run |
|---|---|
| start the app | `docker compose up -d --build --wait` |
| stop it (data is kept) | `docker compose down` |
| see the logs | `docker compose logs -f` (Ctrl+C to stop following) |
| use the CLI | `docker compose run --rm cli apartment list` |
| run the tests | `docker compose --profile test run --rm --build tests` |
| delete all data | `docker compose down -v` |

More about the containers, data, secrets and upgrading from older versions: [documentation/docker.md](documentation/docker.md).

## Using the app

| Page | URL | What you can do |
|---|---|---|
| Apartments | <http://localhost:8000/> | List apartments, search availability, add an apartment |
| Apartment | `/apartments/{id}` | See its bookings, book it, edit it, remove it |
| Bookings | <http://localhost:8000/bookings> | List and filter bookings, create a booking |
| Booking | `/bookings/{id}` | Change dates, apartment or guest, cancel |
| API docs | <http://localhost:8000/api/docs> | Interactive API reference (Swagger UI) |

The rules, enforced the same way for the pages, the API and the CLI:

- Dates are `YYYY-MM-DD`. Check-out is exclusive: a stay from `2026-11-01` to `2026-11-05` is four nights, so back-to-back stays are allowed.
- Overlapping active bookings for the same apartment are rejected.
- Cancelled bookings free their dates, can't be changed, and are hidden unless you ask for them.
- Apartments with active bookings can't be removed.
- Names can't be blank, rooms must be at least 1, and prices can't be negative.

## Architecture

A **frontend** and two **microservices** behind an **NGINX gateway**. Each service has its own SQLite database; they talk through **RabbitMQ** (pub/sub) and, where a rule needs a strict answer, over HTTP:

```
                         browser / CLI
                               │
                     ┌─────────▼─────────┐
                     │   nginx gateway   │  /                → frontend/ (static HTML + JS)
                     │                   │  /api/apartments  → apartments
                     └───┬───────────┬───┘  /api/…           → bookings
                         ▼           ▼
                   apartments ◄──► bookings        HTTP: delete check, read-through
                         │           │
              apartments.db         bookings.db    (each: data + outbox + replica)
                         │           │
              apartments-worker   bookings-worker  outbox relay + event consumer
                         └─► RabbitMQ ◄─┘          events in both directions
```

- The **frontend** is plain HTML pages; their JavaScript loads and changes all data through the REST API.
- The **apartments service** owns apartments. It answers availability search from its copy (replica) of the bookings, and asks the booking service over HTTP before deleting an apartment.
- The **booking service** owns bookings. It checks that an apartment exists against its copy of the apartments, so booking keeps working while the apartments service is down.
- Every change and its event are saved in one transaction (outbox); each service's worker publishes the events and applies the other service's events to its replica, which can lag a moment behind.

How it got here: [documentation/microservices-plan.md](documentation/microservices-plan.md) and [documentation/gateway-plan.md](documentation/gateway-plan.md).

## REST API

Base URL: `http://localhost:8000/api`. The full specification, with schemas, examples and errors, is [`bookings_service/openapi.yaml`](bookings_service/openapi.yaml), also served at [`/api/openapi.yaml`](http://localhost:8000/api/openapi.yaml) and rendered at [`/api/docs`](http://localhost:8000/api/docs).

| Method | Path | Description | Success |
|---|---|---|---|
| GET | `/apartments` | List apartments. `?from=&to=` searches availability, `?min_rooms=` filters | 200 |
| POST | `/apartments` | Add an apartment | 201 + `Location` |
| GET | `/apartments/{id}` | Show an apartment | 200 |
| PATCH | `/apartments/{id}` | Update the fields sent | 200 |
| DELETE | `/apartments/{id}` | Remove an apartment | 204 |
| GET | `/bookings` | List bookings. Filters: `apartment_id`, `guest`, `include_cancelled=true` | 200 |
| POST | `/bookings` | Create a booking | 201 + `Location` |
| GET | `/bookings/{id}` | Show a booking | 200 |
| PATCH | `/bookings/{id}` | Change a booking, or cancel it with `{"status": "cancelled"}` | 200 |
| GET | `/health` | Health check | 200 |

Errors share one shape, e.g. `{"error": {"code": "conflict", "message": "Apartment 1 is already booked from 2026-11-01 to 2026-11-05 (booking 1)"}}`:

| Status | `code` | When |
|---|---|---|
| 400 | `validation_error` | Bad JSON, unknown or missing fields, wrong types, invalid dates or values |
| 404 | `not_found` | The apartment or booking doesn't exist |
| 405 | `method_not_allowed` | The method isn't supported on that URL |
| 409 | `conflict` | Overlapping booking, removing a booked apartment, changing a cancelled booking |
| 415 | `unsupported_media_type` | A request body wasn't sent as `application/json` |
| 503 | `service_unavailable` | A service the request needs can't be reached |

For example:

```sh
curl -X POST http://localhost:8000/api/apartments -H 'Content-Type: application/json' \
  -d '{"name": "Loft", "address": "1 Beach Rd", "rooms": 2, "price": 80}'
curl 'http://localhost:8000/api/apartments?from=2026-11-03&to=2026-11-04'
```

## Command-line interface

The CLI is a client of the REST API: it talks to the running app (`--api URL`, default `http://localhost:8000`). With Docker, put the command after `docker compose run --rm cli`; with Python, use `python3 booking.py`.

```
Usage: booking.py COMMAND [OPTIONS]
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
```

Add `--json` to any command for JSON output. Invalid operations exit with code 1.

## Development

Requires Python 3.9+. To run the app without Docker:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python3 -m devstack            # the app on http://localhost:8000; Ctrl+C to stop
```

`devstack` runs the same code as Docker in one process, minus NGINX and RabbitMQ: both services as separate HTTP servers, a Python stand-in for the gateway with the same routes, and events handed straight to the other service. Data is kept in `./apartments.db` and `./bookings.db`. The tests use it too.

| Tests | Command |
|---|---|
| unit tests | `python3 -m unittest -v` |
| HTTP API tests (black box, only HTTP) | `python3 -m unittest discover -s api_tests -v` |
| the same, against a running app | `API_BASE_URL=http://localhost:8000 python3 -m unittest discover -s api_tests -v` |
| browser tests (Playwright, Python 3.10+) | `pip install -r requirements-e2e.txt`, `python3 -m playwright install chromium` once, then `python3 -m unittest discover -s e2e -v` (`HEADED=1` to watch) |
| smoke test of a running app | `python3 scripts/smoke_test.py http://localhost:8000` |

To import data from the old JSON version: `python3 -m bookings_service.migrate data.json`.

CI runs all of these on GitHub Actions and GitLab, plus end-to-end checks against the Docker Compose stack: see [documentation/ci.md](documentation/ci.md).

## Project layout

```
frontend/            static pages: one HTML file per page, static/app.js, static/pages/*.js, style.css
nginx/               gateway configuration
apartments_service/  apartments service: /api/apartments, availability search
bookings_service/    booking service: /api/bookings, the API spec (openapi.yaml)
common/              shared by both services: database, events, outbox, RabbitMQ, HTTP helpers
booking_cli/         command-line client (booking.py)
devstack/            the whole app without Docker, for development and tests
tests/               unit tests
api_tests/           black-box HTTP tests
e2e/                 browser tests (Playwright)
scripts/             smoke test
documentation/       plans, Docker and CI details
```

Each service has the same shape: `app.py` (Flask app), `service.py` (rules), a repository on its SQLite database with the event outbox and the other service's replica, `consumer.py` (applies the other service's events) and `worker.py` (relay + consumer process).

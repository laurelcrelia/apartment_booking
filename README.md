# Apartment Booking

Authors: Laurel Matt and Kleidi Gjeta 

> This app was made as an exercise for the course Continuous Integration and Delivery (76106B) at the Free University of Bozen-Bolzano (unibz).

Web app for managing apartments and bookings, with availability search and overlap prevention. It has web forms for every workflow, a REST API documented with OpenAPI, and a command-line interface. All three share the same data.

## Quick start (Docker)

Requires Docker with Compose v2. No local Python needed. From a fresh checkout:

```sh
git clone https://github.com/laurelcrelia/apartment_booking.git
cd apartment_booking
```

| Task | Command |
|---|---|
| Start the app | `docker compose up -d --build --wait` |
| Open the app | <http://localhost:8000> |
| Stop the app (data is kept) | `docker compose down` |
| Run the tests | `docker compose --profile test run --rm --build tests` |
| View server logs | `docker compose logs -f web` |
| Delete all data | `docker compose down -v` |

`--wait` returns once the app passes its health check (`/api/health`). The app listens only on `127.0.0.1`, so it can't be reached from other machines.

Data is stored in the `booking-data` Docker volume as `/data/data.json`. It survives `docker compose down` and image rebuilds; only `docker compose down -v` deletes it.

## Using the web app

| Page | URL | What you can do |
|---|---|---|
| Apartments | <http://localhost:8000/> | List apartments, search availability, add an apartment |
| Apartment | `/apartments/{id}` | See its bookings, book it, edit it, remove it |
| Bookings | <http://localhost:8000/bookings> | List and filter bookings, create a booking |
| Booking | `/bookings/{id}` | Change dates, apartment or guest, cancel |
| API docs | <http://localhost:8000/api/docs> | Interactive API reference (Swagger UI) |

The forms send JSON to the REST API below and show its error messages inline, so the browser and API clients follow exactly the same rules. JavaScript must be enabled.

## Rules

- Dates are `YYYY-MM-DD`. Check-out is exclusive: a stay from `2026-11-01` to `2026-11-05` is four nights, so back-to-back stays are allowed.
- Overlapping active bookings for the same apartment are rejected.
- Cancelled bookings free their dates, can't be changed, and are hidden unless you ask for them.
- Apartments with active bookings can't be removed.
- Names can't be blank, rooms must be at least 1, and prices can't be negative.

## REST API

Base URL: `http://localhost:8000/api`. The full specification, with schemas, examples and errors, is [`apartment_booking/openapi.yaml`](apartment_booking/openapi.yaml), served at [`/api/openapi.yaml`](http://localhost:8000/api/openapi.yaml) and rendered at [`/api/docs`](http://localhost:8000/api/docs).

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

Errors use one shape, for example:

```json
{"error": {"code": "conflict", "message": "Apartment 1 is already booked from 2026-11-01 to 2026-11-05 (booking 1)"}}
```

| Status | `code` | When |
|---|---|---|
| 400 | `validation_error` | Bad JSON, unknown or missing fields, wrong types, invalid dates or values |
| 404 | `not_found` | The apartment or booking doesn't exist |
| 405 | `method_not_allowed` | The method isn't supported on that URL |
| 409 | `conflict` | Overlapping booking, removing a booked apartment, changing a cancelled booking |
| 415 | `unsupported_media_type` | A request body wasn't sent as `application/json` |

Examples:

```sh
curl -i -X POST http://localhost:8000/api/apartments \
  -H 'Content-Type: application/json' \
  -d '{"name": "Loft", "address": "1 Beach Rd", "rooms": 2, "price": 80}'

curl -i -X POST http://localhost:8000/api/bookings \
  -H 'Content-Type: application/json' \
  -d '{"apartment_id": 1, "check_in": "2026-11-01", "check_out": "2026-11-05", "guest": "Ann"}'

curl 'http://localhost:8000/api/apartments?from=2026-11-03&to=2026-11-04'

curl -X PATCH http://localhost:8000/api/bookings/1 \
  -H 'Content-Type: application/json' -d '{"status": "cancelled"}'
```

## Command-line interface

The CLI uses the same data as the web app. With Docker, put the command after `docker compose run --rm booking`:

```sh
docker compose run --rm booking --help
docker compose run --rm booking apartment add --name Loft --address "1 Beach Rd"
docker compose run --rm booking apartment list
```

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

## Running without Docker

Requires Python 3.9+.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

flask --app apartment_booking.web run --port 8000   # web app on http://localhost:8000
python3 booking.py --help                           # CLI
python3 -m unittest -v                              # tests
```

Without Docker, data is stored in `./data.json`. Override it with the `APT_DATA_FILE` environment variable, or `--data PATH` for the CLI.

`scripts/smoke_test.py` runs every workflow against a running server and cleans up afterwards: `python3 scripts/smoke_test.py http://localhost:8000`.

## Project layout

```
apartment_booking/
  service.py      business rules (shared by web app and CLI)
  storage.py      JSON file storage
  api.py          REST API under /api
  openapi.yaml    API specification
  web.py          Flask app factory and HTML pages
  templates/      page templates
  static/         CSS and the JavaScript that sends forms to the API
  cli.py          command-line interface
tests/            unit tests (service, API, pages, OpenAPI spec)
scripts/          end-to-end smoke test
```

The server runs as a single gunicorn worker with four threads. Requests are serialized with a lock so concurrent writes to the JSON file can't overwrite each other. Don't increase the worker count without moving to a real database.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and on every pull request:

- **Docker tests**: builds the test image for each Python version from 3.9 to 3.13 and runs the unit tests inside it.
- **Code coverage**: measures coverage with [coverage.py](https://coverage.readthedocs.io/) and fails if it drops below 90%. The report is shown in the run summary and uploaded as the `coverage-html` artifact.
- **Docker Compose end-to-end**: starts the app with Compose, runs `scripts/smoke_test.py`, restarts it to check that data persists, and runs the CLI and the tests through Compose.

To build for a specific Python version locally:

```sh
docker build --build-arg PYTHON_VERSION=3.9 -t apartment-booking:py3.9 .
```

## GitLab CI

The project is mirrored to [gitlab.inf.unibz.it](https://gitlab.inf.unibz.it/LaurelCrelia.Matt/apartment_booking). `.gitlab-ci.yml` runs the same three jobs as GitHub Actions on a self-hosted runner using the **shell executor**: jobs run directly on the runner machine and use its Docker, so no Docker-in-Docker is needed.

Each job uses its own Compose project, data volume (`booking-data-ci-<job id>`) and port (`18000`), so CI never touches the app or data you run yourself on the same machine. Override them for your own use with `APP_PORT` and `BOOKING_VOLUME`.

Runner setup (macOS, once):

1. In GitLab, go to **Settings → CI/CD → Runners → New project runner**. Add the tag `local-docker`, leave "Run untagged jobs" unchecked, check "Protected", and copy the token.
2. Register the runner. `--env` gives jobs a `PATH` that includes Docker:
   ```sh
   gitlab-runner register --non-interactive \
     --url https://gitlab.inf.unibz.it --token <glrt-token> \
     --executor shell --name "$(hostname -s)" \
     --env "PATH=$HOME/.docker/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   ```
3. Start it: `brew services start gitlab-runner`, then check with `gitlab-runner verify`.

Keep `concurrent = 1` in `~/.gitlab-runner/config.toml`. Jobs run with your user's permissions, so the runner is protected and project-only: only people who can push to `main` can trigger it. Stop it when not needed with `brew services stop gitlab-runner`.

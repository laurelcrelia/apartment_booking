# Apartment Booking

Authors: Laurel Matt and Kleidi Gjeta 

> This app was made as an exercise for the course Continuous Integration and Delivery (76106B) at the Free University of Bozen-Bolzano (unibz).

Web app for managing apartments and bookings, with availability search and overlap prevention. It has web forms for every workflow, a REST API documented with OpenAPI, and a command-line interface. All three share the same data.

The backend is being split into microservices (see [documentation/microservices-plan.md](documentation/microservices-plan.md)). Apartments already run as their own **apartments service** with their own database. The web app owns bookings, serves the UI and the public REST API, and calls the apartments service over HTTP for apartment changes. Each service publishes its changes as events through RabbitMQ, and keeps a local copy (replica) of the other service's data from those events. The booking service checks that an apartment exists against its copy of the apartments, so booking keeps working while the apartments service is down. The apartments service answers availability search from its copy of the bookings, and asks the booking service over HTTP before deleting an apartment, so an apartment with active bookings can never be deleted:

```
browser ──► nginx ──► web (apartment_booking) ──HTTP──► apartments (apartments_service)
                      bookings.db + outbox                 apartments.db + outbox
                      └ apartments replica                 └ bookings replica
                            ▲  │                                 │  ▲
                            │  ▼                                 ▼  │
                      bookings-worker ◄──── RabbitMQ ────► apartments-worker
                       booking events out, apartment events in (and the reverse)
```

NGINX is the gateway and the only way in from outside. It routes `/api/apartments` to the apartments service and everything else (bookings, pages, the rest of the API) to `web`; [documentation/gateway-plan.md](documentation/gateway-plan.md) describes the next steps.

The copy can lag a moment behind: an apartment created a second ago may not show up in availability search yet (booking it works right away).

## Quick start (Docker)

Requires Docker with Compose v2. No local Python needed. From a fresh checkout:

```sh
git clone https://github.com/laurelcrelia/apartment_booking.git
cd apartment_booking
printf 'RABBITMQ_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env   # once: creates your local secrets
```

Compose won't start without `.env`; see [Secrets](#secrets).

| Task | Command |
|---|---|
| Start the app | `docker compose up -d --build --wait` |
| Open the app | <http://localhost:8000> |
| Stop the app (data is kept) | `docker compose down` |
| Run the tests | `docker compose --profile test run --rm --build tests` |
| View server logs | `docker compose logs -f nginx web apartments` (Ctrl+C to stop following) |
| Delete all data | `docker compose down -v` |

Compose starts six containers:

| Container | What it does |
|---|---|
| `nginx` | gateway: the only published port; routes `/api/apartments` to `apartments`, the rest to `web` |
| `web` | web UI and the booking service (`/api/bookings`) |
| `apartments` | apartments service (`/api/apartments`, including availability search) |
| `apartments-worker` | publishes the apartments service's events, and updates its bookings replica from booking events |
| `bookings-worker` | publishes the booking service's events, and updates its apartments replica from apartment events |
| `rabbitmq` | message broker; management UI on <http://localhost:15672> (log in with `RABBITMQ_USER`, default `booking`, and your `RABBITMQ_PASSWORD` from `.env`) |

`--wait` returns once everything is up and healthy. Each worker runs two tasks, an outbox relay and an event consumer, and counts as healthy only while both are connected to RabbitMQ and working: each task writes a heartbeat file, and the health check (`python -m common.health`) fails if either is older than 30 seconds. If a task stops for good, the worker exits and Docker restarts it. Only `nginx` and the RabbitMQ UI are published, on `127.0.0.1`, so they can't be reached from other machines. When a service is down, `nginx` answers its part of the API with the usual JSON `503 service_unavailable`, and the other service keeps working: with `apartments` down, bookings (including creating them) still work; with `web` down, apartments and availability search still work, but deleting an apartment answers `503`, since it needs the booking service's check.

Each service has its own volume and SQLite database: bookings in `booking-data` (`/data/bookings.db`) and apartments in `apartments-data` (`/data/apartments.db`); RabbitMQ keeps its queues in `rabbitmq-data`. They survive `docker compose down` and image rebuilds; only `docker compose down -v` deletes them.

After an upgrade, apartments and bookings that existed before their events did are announced once automatically when their worker first starts, so the replicas learn about them.

### Secrets

The only secret is the RabbitMQ login. It is never stored in the repository: Compose reads it from a `.env` file next to `compose.yaml` (or from environment variables), and refuses to start if `RABBITMQ_PASSWORD` is missing. `.env` is git-ignored and excluded from the Docker build context, so it can't end up in a commit or an image. `.env.example` lists the settings:

| Variable | Default | Meaning |
|---|---|---|
| `RABBITMQ_PASSWORD` | (required) | RabbitMQ password; letters and digits only, since it goes into an `amqp://` URL |
| `RABBITMQ_USER` | `booking` | RabbitMQ user name |

The workers get the login as `RABBITMQ_URL`, which Compose builds from these. CI generates a new random password for every run, so the pipelines need no stored secret.

RabbitMQ only applies the login when its `rabbitmq-data` volume is first created. To change the password later, change it in RabbitMQ too, then restart the services that connect:

```sh
docker compose exec rabbitmq rabbitmqctl change_password booking 'NEW_PASSWORD'
# put NEW_PASSWORD into .env, then:
docker compose up -d
```

**Upgrading from a version with the built-in `booking`/`booking` login:** either keep that password (`RABBITMQ_PASSWORD=booking` in `.env`) or change it as above.

**Upgrading from the JSON version** (everything in `/data/data.json`): start the new version once so both volumes exist, then copy the data in, keeping all IDs:

```sh
docker compose up -d --build --wait
docker compose run --rm --no-deps -v apartments-data:/apartments --entrypoint python booking \
  -m apartment_booking.migrate /data/data.json --apartments-db /apartments/apartments.db
```

**Upgrading from the first SQLite version** (`apartments.db` still in `booking-data`): move it to the apartments service's volume:

```sh
docker compose up -d --build --wait
docker compose stop apartments
docker compose run --rm --no-deps -v booking-data:/old --entrypoint sh apartments \
  -c 'rm -f /data/apartments.db*; cp /old/apartments.db /data/'
docker compose start apartments
```

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
| 503 | `service_unavailable` | The apartments service, which the request needs, can't be reached |

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

python3 -m apartment_booking.local --port 8000      # app on http://localhost:8000
python3 booking.py --help                           # CLI
python3 -m unittest -v                              # tests
```

`apartment_booking.local` runs both services in one process behind a small Python stand-in for the NGINX gateway (same routes), with apartments in `./apartments.db` and bookings in `./bookings.db`; events go straight from each outbox to the other side's replica, with no RabbitMQ needed. That is the simplest way to develop. To run the services separately, as deployed, use Docker Compose.

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `BOOKINGS_DB` | web, CLI | `bookings.db` | bookings database |
| `APARTMENTS_URL` | web, CLI | unset | apartments service to call; if unset, apartments are served in-process |
| `BOOKINGS_URL` | apartments service | (required) | booking service to ask for active bookings before deleting an apartment |
| `APARTMENTS_DB` | apartments service and worker, or web/CLI without `APARTMENTS_URL` | `apartments.db` | apartments database |
| `RABBITMQ_URL` | workers | (required) | RabbitMQ to publish to or consume from, including the login |
| `TRUSTED_PROXIES` | web | `0` | number of reverse proxies in front of the app whose `X-Forwarded-*` headers to trust; Compose sets `1` for nginx. Leave it at `0` when the app is reachable directly |

The CLI takes the same settings as `--bookings-db`, `--apartments-url` and `--apartments-db`. To import an old `data.json`, run `python3 -m apartment_booking.migrate data.json`.

`scripts/smoke_test.py` runs every workflow against a running server and cleans up afterwards: `python3 scripts/smoke_test.py http://localhost:8000`.

## HTTP API tests

`api_tests/` is a black-box test suite for the REST API. It only sends HTTP requests, never imports the app's internals, creates its own data with unique names, and cleans up afterwards. That lets the same tests check the current app and, unchanged, the app after it is split into microservices (see [documentation/microservices-plan.md](documentation/microservices-plan.md)).

```sh
python -m unittest discover -s api_tests -v                                      # app started in-process on a free port
API_BASE_URL=http://localhost:8000 python -m unittest discover -s api_tests -v   # a running app, e.g. docker compose
```

Like `e2e/`, the folder has no `__init__.py`, so the plain unit test run doesn't include it.

## Browser tests (Playwright)

`e2e/` holds end-to-end tests that drive the web UI in Chromium with [Playwright](https://playwright.dev/python/). They start the app on a free local port with fresh in-memory data for every test, so they never touch your databases. They need Python 3.10+.

```sh
pip install -r requirements-e2e.txt
python -m playwright install chromium        # once; add --with-deps on Linux

python -m unittest discover -s e2e -v        # run headless
HEADED=1 python -m unittest discover -s e2e  # watch them in a browser window
```

`e2e/` has no `__init__.py`, so a plain `python -m unittest` (and the Docker test image) doesn't pick these tests up and doesn't need a browser.

## Project layout

```
apartment_booking/  web app: UI, public REST API, bookings
  service.py      booking rules (shared by web app and CLI)
  repos.py        SQLite repository for bookings, with the event outbox and the apartments replica
  apartments_client.py  HTTP client for the apartments service
  local.py        both services behind a stand-in gateway, for development and tests
  consumer.py     applies apartment events to the apartments replica
  worker.py       relay + consumer (process: bookings-worker)
  inprocess.py    apartments service and event delivery inside this process
  migrate.py      one-off import of the old data.json
  api.py          REST API under /api
  openapi.yaml    API specification
  web.py          Flask app factory and HTML pages
  templates/      page templates
  static/         CSS and the JavaScript that sends forms to the API
  cli.py          command-line interface
apartments_service/  apartments service: internal JSON API for apartments
  app.py          Flask app (/api/apartments, /api/health)
  bookings_client.py  HTTP client for the booking service (delete check)
  service.py      apartment rules
  repo.py         SQLite repository for apartments, with the event outbox and the bookings replica
  consumer.py     applies booking events to the bookings replica
  worker.py       relay + consumer (process: apartments-worker)
common/           shared by both services
  events.py       event format and types
  outbox.py       transactional outbox
  relay.py        publishes a service's outbox
  worker.py       runs a worker's tasks side by side
  rabbitmq.py     publishing, consuming, reconnecting (pika)
  health.py       heartbeat health checks for the background workers
  db.py           SQLite connections and transactions
  http.py         JSON errors and request parsing
  errors.py       errors shown to the user
  client.py       base for the HTTP clients between services
  dates.py        date parsing and ranges
tests/            unit tests (service, API, pages, OpenAPI spec)
api_tests/        black-box HTTP tests for the REST API
e2e/              browser tests (Playwright, Chromium)
scripts/          end-to-end smoke test
nginx/            gateway configuration (default.conf)
```

Apartments and bookings are kept in separate SQLite databases owned by separate services. Each write runs in its own transaction, and booking writes take the database's write lock before checking for overlaps, so two requests can never double-book an apartment. That makes it safe to run several gunicorn workers (the Docker image uses two, with four threads each).

A plan to split apartments into their own microservice (SQLite per service, HTTP plus RabbitMQ events) is described, with architecture diagrams, in [documentation/microservices-plan.md](documentation/microservices-plan.md). The next stage, an NGINX gateway, a static frontend and pub/sub in both directions, is planned in [documentation/gateway-plan.md](documentation/gateway-plan.md).

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and on every pull request:

- **Docker tests**: builds the test image for each Python version from 3.9 to 3.13 and runs the unit tests inside it.
- **Code coverage**: measures coverage with [coverage.py](https://coverage.readthedocs.io/) and fails if it drops below 90%. The report is shown in the run summary and uploaded as the `coverage-html` artifact.
- **HTTP API tests**: runs `api_tests/` against the app started in-process.
- **Browser tests**: installs Playwright and Chromium and runs the `e2e/` tests against the web UI.
- **Docker Compose end-to-end**: starts the app with Compose, runs `scripts/smoke_test.py` and the `api_tests/` suite against it, restarts it to check that data persists, checks that an apartment change made while the bookings worker is stopped reaches the booking side once it is back, that booking events reach the apartments service, stops the apartments service to check for `503` while bookings keep working, checks that only the gateway is published and that with `web` stopped apartments keep working while bookings and deletes answer JSON `503`, and runs the CLI and the tests through Compose.

To build for a specific Python version locally:

```sh
docker build --build-arg PYTHON_VERSION=3.9 -t apartment-booking:py3.9 .
```

## GitLab CI

The project is mirrored to [gitlab.inf.unibz.it](https://gitlab.inf.unibz.it/LaurelCrelia.Matt/apartment_booking). `.gitlab-ci.yml` runs the same jobs as GitHub Actions on a self-hosted runner using the **shell executor**: jobs run directly on the runner machine and use its Docker, so no Docker-in-Docker is needed.

Each job uses its own Compose project, volumes (`booking-data-ci-<job id>`, `apartments-data-ci-<job id>`, `rabbitmq-data-ci-<job id>`) and ports (app `18000`, RabbitMQ UI `25672`), so CI never touches the app or data you run yourself on the same machine. The Compose job writes its own `.env` with a throwaway RabbitMQ password. Override these for your own use with `APP_PORT`, `RABBITMQ_UI_PORT`, `BOOKING_VOLUME`, `APARTMENTS_VOLUME` and `RABBITMQ_VOLUME`.

The pipeline runs for merge requests, the default branch and manual runs (**Build → Pipelines → New pipeline**); plain pushes to other branches don't start it. GitHub Actions likewise runs only for pushes to `main` and for pull requests.

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

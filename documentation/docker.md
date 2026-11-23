# Running with Docker: details

The [README](../README.md#quick-start) has the commands for everyday use. This page explains what runs, where the data lives, how the secrets work, and how to upgrade from older versions.

## Containers

`docker compose up -d --build --wait` starts six containers and returns once all of them are healthy:

| Container | What it does |
|---|---|
| `nginx` | gateway: the only published port (`127.0.0.1:8000`); serves the frontend, routes `/api/apartments` to `apartments` and the rest of `/api` to `bookings` |
| `apartments` | apartments service (`/api/apartments`, including availability search) |
| `bookings` | booking service (`/api/bookings`) |
| `apartments-worker` | publishes the apartments service's events, and updates its bookings replica from booking events |
| `bookings-worker` | publishes the booking service's events, and updates its apartments replica from apartment events |
| `rabbitmq` | message broker; management UI on <http://localhost:15672> (user `booking`, password from `.env`) |

Only `nginx` and the RabbitMQ UI are published, on `127.0.0.1`, so they can't be reached from other machines.

**Health checks.** Each worker runs two tasks, an outbox relay and an event consumer, and counts as healthy only while both are connected to RabbitMQ and working: each task writes a heartbeat file, and the health check (`python -m common.health`) fails if either is older than 30 seconds. If a task stops for good, the worker exits and Docker restarts it.

**When a service is down,** `nginx` answers its part of the API with the usual JSON `503 service_unavailable`, and the other service keeps working:

- with `apartments` down, bookings (including creating them) still work;
- with `bookings` down, apartments and availability search still work, but deleting an apartment answers `503`, since it needs the booking service's check.

## Data

Each service has its own volume and SQLite database:

| Volume | Contents |
|---|---|
| `booking-data` | `/data/bookings.db` |
| `apartments-data` | `/data/apartments.db` |
| `rabbitmq-data` | RabbitMQ's queues |

They survive `docker compose down` and image rebuilds; only `docker compose down -v` deletes them.

## Secrets

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

## Upgrading from older versions

Data is kept across upgrades. Apartments and bookings that existed before their events did are announced once automatically when their worker first starts, so the replicas learn about them. A few versions need a one-time step:

**From the version with the `web` container** (before the cleanup): the service is now called `bookings`. Remove the old container with `docker compose up -d --build --wait --remove-orphans`. The CLI is now `docker compose run --rm cli ...`.

**From a version with the built-in `booking`/`booking` RabbitMQ login:** either keep that password (`RABBITMQ_PASSWORD=booking` in `.env`) or change it as described under [Secrets](#secrets).

**From the JSON version** (everything in `/data/data.json`): start the new version once so both volumes exist, then copy the data in, keeping all IDs:

```sh
docker compose up -d --build --wait
docker compose run --rm --no-deps -v apartments-data:/apartments --entrypoint python bookings \
  -m bookings_service.migrate /data/data.json --apartments-db /apartments/apartments.db
```

**From the first SQLite version** (`apartments.db` still in `booking-data`): move it to the apartments service's volume:

```sh
docker compose up -d --build --wait
docker compose stop apartments
docker compose run --rm --no-deps -v booking-data:/old --entrypoint sh apartments \
  -c 'rm -f /data/apartments.db*; cp /old/apartments.db /data/'
docker compose start apartments
```

## Settings

The services are configured through environment variables; `compose.yaml` sets them for Docker.

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `APARTMENTS_DB` | apartments service and worker | `apartments.db` | apartments database |
| `BOOKINGS_DB` | booking service and worker | `bookings.db` | bookings database |
| `APARTMENTS_URL` | booking service | (required) | apartments service, to look up apartments its replica doesn't know yet |
| `BOOKINGS_URL` | apartments service | (required) | booking service, asked for active bookings before deleting an apartment |
| `RABBITMQ_URL` | workers | (required) | RabbitMQ to publish to and consume from, including the login |
| `TRUSTED_PROXIES` | both services | `0` | number of reverse proxies in front whose `X-Forwarded-*` headers to trust; Compose sets `1` for nginx. Leave it at `0` when a service is reachable directly |
| `API_URL` | CLI | `http://localhost:8000` | the app the CLI talks to |
| `APP_PORT` | Compose | `8000` | port the app is published on |

## Building for a specific Python version

```sh
docker build --build-arg PYTHON_VERSION=3.9 -t apartment-booking:py3.9 .
```

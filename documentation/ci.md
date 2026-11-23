# Continuous integration

Both pipelines run the same jobs: **GitHub Actions** (`.github/workflows/ci.yml`) for pushes to `main` and for pull requests, and **GitLab CI** (`.gitlab-ci.yml`) on a self-hosted runner for merge requests, the default branch and manual runs. Plain pushes to other branches start neither.

## Jobs

- **Docker tests**: builds the test image for each Python version from 3.9 to 3.13 and runs the unit tests inside it.
- **Code coverage**: measures coverage with [coverage.py](https://coverage.readthedocs.io/) and fails if it drops below 90%. GitHub shows the report in the run summary and uploads it as the `coverage-html` artifact.
- **HTTP API tests**: runs `api_tests/` against the app started with `devstack`.
- **Browser tests**: installs Playwright and Chromium and runs the `e2e/` tests against the frontend.
- **Docker Compose end-to-end**: starts the whole app with Compose and checks it from outside:
  - `scripts/smoke_test.py` and the `api_tests/` suite against it;
  - data survives a restart;
  - an apartment change made while the bookings worker is stopped reaches the booking side once it is back, and booking events reach the apartments service;
  - with the apartments service stopped, the API answers `503` while bookings keep working;
  - only the gateway is published, and with the booking service stopped apartments keep working while bookings and deletes answer JSON `503`;
  - the CLI works through the gateway, and the tests run via Compose.

## GitLab

The project is mirrored to [gitlab.inf.unibz.it](https://gitlab.inf.unibz.it/LaurelCrelia.Matt/apartment_booking). Its runner uses the **shell executor**: jobs run directly on the runner machine and use its Docker, so no Docker-in-Docker is needed.

Each job uses its own Compose project, volumes (`booking-data-ci-<job id>`, `apartments-data-ci-<job id>`, `rabbitmq-data-ci-<job id>`) and ports (app `18000`, RabbitMQ UI `25672`), so CI never touches the app or data you run yourself on the same machine. The Compose job writes its own `.env` with a throwaway RabbitMQ password. Override these for your own use with `APP_PORT`, `RABBITMQ_UI_PORT`, `BOOKING_VOLUME`, `APARTMENTS_VOLUME` and `RABBITMQ_VOLUME`.

To start a pipeline by hand: **Build → Pipelines → New pipeline**.

### Runner setup (macOS, once)

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

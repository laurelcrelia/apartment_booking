ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APARTMENTS_DB=/data/apartments.db \
    BOOKINGS_DB=/data/bookings.db

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && mkdir /data \
    && chown app:app /data

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY booking.py ./
COPY common/ ./common/
COPY apartments_service/ ./apartments_service/
COPY bookings_service/ ./bookings_service/
COPY booking_cli/ ./booking_cli/

# Test image: adds dev dependencies and the tests. Build with --target test.
FROM base AS test
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY tests/ ./tests/
# Tests run the whole app with devstack, including the static frontend.
COPY devstack/ ./devstack/
COPY frontend/ ./frontend/
USER app
ENTRYPOINT ["python", "-m", "unittest"]
CMD ["-v"]

# Runtime image (default): serves the booking service on port 8000. The same image runs
# the apartments service with a different command (see compose.yaml).
FROM base AS runtime
USER app
VOLUME ["/data"]
EXPOSE 8000
# Several workers are safe: every write runs in its own SQLite transaction.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", \
     "--access-logfile", "-", "bookings_service.app:create_app()"]

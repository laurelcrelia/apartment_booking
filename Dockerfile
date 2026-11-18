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
COPY apartment_booking/ ./apartment_booking/

# Test image: adds dev dependencies and the tests. Build with --target test.
FROM base AS test
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY tests/ ./tests/
USER app
ENTRYPOINT ["python", "-m", "unittest"]
CMD ["-v"]

# Runtime image (default): serves the web app on port 8000.
FROM base AS runtime
USER app
VOLUME ["/data"]
EXPOSE 8000
# Several workers are safe: every write runs in its own SQLite transaction.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", \
     "--access-logfile", "-", "apartment_booking.web:create_app()"]

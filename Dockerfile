FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APT_DATA_FILE=/data/data.json

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && mkdir /data \
    && chown app:app /data

COPY booking.py ./
COPY apartment_booking/ ./apartment_booking/
COPY tests/ ./tests/

USER app

VOLUME ["/data"]

ENTRYPOINT ["python", "booking.py"]
CMD ["--help"]

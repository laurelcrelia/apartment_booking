"""RabbitMQ plumbing with pika: publishing, consuming and reconnecting.

This module needs a running broker, so it is left out of the unit test
coverage (see .coveragerc) and exercised by the Docker Compose CI job instead.
Everything with logic worth unit testing (outbox, relay, event handling) is
kept in modules that don't import pika.
"""
from __future__ import annotations

import logging
import time

import pika
from pika.exceptions import AMQPError

from .events import EXCHANGE, encode

log = logging.getLogger(__name__)


def connect(url: str):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()
    channel.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    return connection, channel


class PikaPublisher:
    def __init__(self, url: str):
        self.connection, self.channel = connect(url)
        self.channel.confirm_delivery()

    def publish(self, event: dict) -> None:
        # Returns once the broker has confirmed the message. mandatory=True: if
        # no queue is bound yet, pika raises UnroutableError instead of the
        # broker silently dropping the message, so the outbox row stays pending.
        self.channel.basic_publish(
            EXCHANGE, event["type"], encode(event),
            pika.BasicProperties(content_type="application/json", delivery_mode=2,
                                 message_id=event["event_id"]),
            mandatory=True)

    def sleep(self, seconds: float) -> None:
        self.connection.sleep(seconds)  # keeps heartbeats going while idle

    def close(self) -> None:
        if self.connection.is_open:
            self.connection.close()


def consume(url: str, queue: str, binding: str, on_message, on_tick=None) -> None:
    """Consume a durable queue bound to EXCHANGE, calling on_message(body) per message.

    A message is acknowledged after on_message returns. If it raises, the
    connection drops and the broker delivers the message again. on_tick() is
    called every few seconds while the connection is healthy.
    """
    connection, channel = connect(url)
    try:
        channel.queue_declare(queue, durable=True)
        channel.queue_bind(queue, EXCHANGE, routing_key=binding)
        channel.basic_qos(prefetch_count=10)

        def callback(ch, method, properties, body):
            on_message(body)
            ch.basic_ack(method.delivery_tag)

        channel.basic_consume(queue, callback)
        log.info("consuming %s (%s on exchange %s)", queue, binding, EXCHANGE)
        while True:
            if on_tick:
                on_tick()
            connection.process_data_events(time_limit=5)  # delivers messages to callback
    finally:
        if connection.is_open:
            connection.close()


def run_forever(work, name: str) -> None:
    """Run work() forever, reconnecting with backoff when the broker is unreachable."""
    delay = 1
    while True:
        started = time.monotonic()
        try:
            work()
        except (AMQPError, OSError) as e:
            log.warning("%s: %s; retrying in %ds", name, str(e) or type(e).__name__, delay)
        if time.monotonic() - started > 60:
            delay = 1
        time.sleep(delay)
        delay = min(delay * 2, 30)

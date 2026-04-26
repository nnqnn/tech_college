from __future__ import annotations

import json
import logging

import pika

from backend.config import load_settings

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )


def main() -> None:
    configure_logging()
    settings = load_settings()

    parameters = pika.URLParameters(settings.rabbitmq_url)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue=settings.event_queue_name, durable=True)

    logger.info("Waiting for events from queue %s", settings.event_queue_name)

    def handle_message(ch, method, properties, body: bytes) -> None:
        del properties
        try:
            event = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            logger.exception("Invalid event payload: %r", body)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        logger.info("Received event: %s", event)
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_qos(prefetch_count=10)
    channel.basic_consume(
        queue=settings.event_queue_name,
        on_message_callback=handle_message,
    )

    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    main()

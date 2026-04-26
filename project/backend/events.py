from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = Lock()

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(_build_event(event_type, payload))

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class RabbitMQEventPublisher:
    def __init__(
        self,
        *,
        rabbitmq_url: str,
        queue_name: str,
        enabled: bool = True,
    ) -> None:
        self._rabbitmq_url = rabbitmq_url
        self._queue_name = queue_name
        self._enabled = enabled
        self._connection = None
        self._channel = None
        self._lock = Lock()

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return

        event = _build_event(event_type, payload)
        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        with self._lock:
            try:
                channel = self._get_channel()
                channel.basic_publish(
                    exchange="",
                    routing_key=self._queue_name,
                    body=body,
                    properties=self._message_properties(),
                )
            except Exception as error:
                logger.warning("RabbitMQ event publish failed: %s", error)
                self._close()

    def _get_channel(self):
        if self._channel is not None and self._channel.is_open:
            return self._channel

        import pika

        parameters = pika.URLParameters(self._rabbitmq_url)
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._channel.queue_declare(queue=self._queue_name, durable=True)
        return self._channel

    @staticmethod
    def _message_properties():
        import pika

        return pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
        )

    def _close(self) -> None:
        try:
            if self._connection is not None and self._connection.is_open:
                self._connection.close()
        finally:
            self._connection = None
            self._channel = None


def _build_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }

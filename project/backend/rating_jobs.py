from __future__ import annotations

import logging
from typing import Any

from backend import metrics
from backend.config import Settings

logger = logging.getLogger(__name__)


class RatingTaskDispatcher:
    def __init__(self, *, settings: Settings, repository: Any) -> None:
        self._settings = settings
        self._repository = repository

    def refresh_user_rating(self, telegram_id: int) -> None:
        if self._send_task("dating.refresh_user_rating", [telegram_id], metric_task="refresh_user"):
            return
        self._fallback_refresh_user(telegram_id, metric_task="refresh_user")

    def process_interaction_event(self, payload: dict[str, Any]) -> None:
        if self._send_task(
            "dating.process_interaction_event",
            [payload],
            metric_task="process_interaction",
        ):
            return

        for key in ("requester", "responder"):
            telegram_id = payload.get(key)
            if telegram_id is not None:
                self._repository.refresh_rating(int(telegram_id))
        metrics.RATING_TASK_FALLBACKS.labels(task="process_interaction").inc()

    def refresh_all_ratings(self) -> int:
        return int(self._repository.refresh_all_ratings())

    def _send_task(self, task_name: str, args: list[Any], *, metric_task: str) -> bool:
        if not self._settings.celery_enabled:
            return False

        try:
            from worker.celery_app import celery_app

            celery_app.send_task(task_name, args=args)
        except Exception as error:
            logger.warning("Celery task enqueue failed task=%s error=%s", task_name, error)
            return False

        metrics.RATING_TASKS_ENQUEUED.labels(task=metric_task).inc()
        return True

    def _fallback_refresh_user(self, telegram_id: int, *, metric_task: str) -> None:
        self._repository.refresh_rating(telegram_id)
        metrics.RATING_TASK_FALLBACKS.labels(task=metric_task).inc()

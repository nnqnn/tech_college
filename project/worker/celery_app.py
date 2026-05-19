from __future__ import annotations

import logging
from typing import Any

from celery import Celery
from celery.signals import worker_ready
from prometheus_client import Counter, start_http_server

from backend.config import load_settings
from backend.logging_config import configure_logging
from backend.storage import PostgresDatingRepository

settings = load_settings()
configure_logging(structured=settings.structured_logging)

logger = logging.getLogger(__name__)

celery_app = Celery(
    "dating",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    beat_schedule={
        "refresh-all-ratings": {
            "task": "dating.refresh_all_ratings",
            "schedule": settings.rating_refresh_interval_seconds,
        }
    },
)

WORKER_TASKS = Counter(
    "dating_worker_tasks_total",
    "Celery tasks grouped by task name and status.",
    ("task", "status"),
)
WORKER_RATING_REFRESHES = Counter(
    "dating_worker_rating_refreshes_total",
    "Rating refreshes performed by Celery workers.",
    ("scope",),
)

_repository: PostgresDatingRepository | None = None
_metrics_started = False


def _get_repository() -> PostgresDatingRepository:
    global _repository
    if _repository is None:
        _repository = PostgresDatingRepository(settings.database_url)
        _repository.initialize()
    return _repository


@worker_ready.connect
def _start_metrics_server(**_: Any) -> None:
    global _metrics_started
    if _metrics_started or not settings.metrics_enabled:
        return

    try:
        start_http_server(settings.worker_metrics_port)
    except OSError as error:
        logger.warning("Worker metrics server was not started: %s", error)
        return
    _metrics_started = True
    logger.info("Worker metrics server started on port %s", settings.worker_metrics_port)


@celery_app.task(name="dating.refresh_user_rating")
def refresh_user_rating(telegram_id: int) -> dict[str, int | bool]:
    task_name = "refresh_user_rating"
    try:
        rating = _get_repository().refresh_rating(int(telegram_id))
    except Exception:
        WORKER_TASKS.labels(task=task_name, status="failed").inc()
        logger.exception("Rating refresh failed telegram_id=%s", telegram_id)
        raise

    WORKER_TASKS.labels(task=task_name, status="succeeded").inc()
    WORKER_RATING_REFRESHES.labels(scope="user").inc()
    return {"telegram_id": int(telegram_id), "refreshed": rating is not None}


@celery_app.task(name="dating.refresh_all_ratings")
def refresh_all_ratings() -> dict[str, int]:
    task_name = "refresh_all_ratings"
    try:
        refreshed = _get_repository().refresh_all_ratings()
    except Exception:
        WORKER_TASKS.labels(task=task_name, status="failed").inc()
        logger.exception("Full rating refresh failed")
        raise

    WORKER_TASKS.labels(task=task_name, status="succeeded").inc()
    WORKER_RATING_REFRESHES.labels(scope="all").inc(refreshed)
    return {"refreshed": refreshed}


@celery_app.task(name="dating.process_interaction_event")
def process_interaction_event(payload: dict[str, Any]) -> dict[str, int]:
    task_name = "process_interaction_event"
    refreshed = 0
    try:
        repository = _get_repository()
        for key in ("requester", "responder"):
            telegram_id = payload.get(key)
            if telegram_id is not None and repository.refresh_rating(int(telegram_id)) is not None:
                refreshed += 1
    except Exception:
        WORKER_TASKS.labels(task=task_name, status="failed").inc()
        logger.exception("Interaction event processing failed payload=%s", payload)
        raise

    WORKER_TASKS.labels(task=task_name, status="succeeded").inc()
    WORKER_RATING_REFRESHES.labels(scope="interaction").inc(refreshed)
    return {"refreshed": refreshed}

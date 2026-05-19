from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.cache import InMemoryCandidateCache
from backend.config import Settings
from backend.events import InMemoryEventPublisher
from backend.main import create_app
from backend.object_storage import InMemoryObjectStorage
from backend.rating_jobs import RatingTaskDispatcher
from backend.storage import InMemoryDatingRepository


@pytest.fixture
def repository() -> InMemoryDatingRepository:
    return InMemoryDatingRepository()


@pytest.fixture
def candidate_cache() -> InMemoryCandidateCache:
    return InMemoryCandidateCache()


@pytest.fixture
def event_publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def object_storage() -> InMemoryObjectStorage:
    return InMemoryObjectStorage()


@pytest.fixture
def client(
    repository: InMemoryDatingRepository,
    candidate_cache: InMemoryCandidateCache,
    event_publisher: InMemoryEventPublisher,
    object_storage: InMemoryObjectStorage,
) -> TestClient:
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        rabbitmq_url="amqp://test:test@localhost:5672/",
        event_queue_name="test.events",
        mq_enabled=False,
        celery_broker_url="amqp://test:test@localhost:5672/",
        celery_result_backend="redis://localhost:6379/15",
        celery_enabled=False,
        rating_refresh_interval_seconds=300,
        candidate_batch_size=3,
        candidate_ttl_seconds=900,
        s3_endpoint_url=None,
        s3_access_key_id="test",
        s3_secret_access_key="test",
        s3_bucket_name="test-photos",
        s3_region_name="us-east-1",
        max_profile_photos=4,
        max_photo_size_bytes=1024 * 1024,
        metrics_enabled=True,
        worker_metrics_port=9101,
        structured_logging=False,
    )
    rating_tasks = RatingTaskDispatcher(settings=settings, repository=repository)
    app = create_app(
        repository=repository,
        candidate_cache=candidate_cache,
        event_publisher=event_publisher,
        object_storage=object_storage,
        rating_tasks=rating_tasks,
        settings=settings,
        run_startup=False,
    )
    return TestClient(app)

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.cache import InMemoryCandidateCache
from backend.config import Settings
from backend.events import InMemoryEventPublisher
from backend.main import create_app
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
def client(
    repository: InMemoryDatingRepository,
    candidate_cache: InMemoryCandidateCache,
    event_publisher: InMemoryEventPublisher,
) -> TestClient:
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        rabbitmq_url="amqp://test:test@localhost:5672/",
        event_queue_name="test.events",
        mq_enabled=False,
        candidate_batch_size=3,
        candidate_ttl_seconds=900,
    )
    app = create_app(
        repository=repository,
        candidate_cache=candidate_cache,
        event_publisher=event_publisher,
        settings=settings,
        run_startup=False,
    )
    return TestClient(app)

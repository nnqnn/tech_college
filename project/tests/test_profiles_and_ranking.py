from fastapi.testclient import TestClient

from backend.cache import InMemoryCandidateCache
from backend.events import InMemoryEventPublisher


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "age": 25,
        "gender": "female",
        "interests": "music, travel",
        "city": "Moscow",
        "age_pref_min": 18,
        "age_pref_max": 35,
        "gender_pref": "any",
        "city_pref": "any",
        "interests_pref": "music",
        "photos_count": 3,
    }
    payload.update(overrides)
    return payload


def _create_profile(client: TestClient, telegram_id: int, **overrides: object) -> dict[str, object]:
    response = client.put(f"/api/v1/profiles/{telegram_id}", json=_profile_payload(**overrides))
    assert response.status_code == 200
    return response.json()


def test_profile_crud(client: TestClient) -> None:
    created = _create_profile(client, 1, city="Moscow")

    assert created["telegram_id"] == 1
    assert created["city"] == "Moscow"
    assert created["profile_completion_pct"] == 100

    fetched = client.get("/api/v1/profiles/1")
    assert fetched.status_code == 200
    assert fetched.json()["telegram_id"] == 1

    listed = client.get("/api/v1/profiles")
    assert listed.status_code == 200
    assert [profile["telegram_id"] for profile in listed.json()] == [1]

    updated = client.put("/api/v1/profiles/1", json={"city": "Saint Petersburg"})
    assert updated.status_code == 200
    assert updated.json()["city"] == "Saint Petersburg"

    deleted = client.delete("/api/v1/profiles/1")
    assert deleted.status_code == 200
    assert deleted.json()["age"] is None

    missing = client.get("/api/v1/profiles/1")
    assert missing.status_code == 404


def test_primary_rating_is_created_after_profile_save(client: TestClient) -> None:
    _create_profile(client, 1, photos_count=4)

    response = client.get("/api/v1/users/1/rating")

    assert response.status_code == 200
    rating = response.json()
    assert rating["primary_score"] >= 90
    assert rating["total_score"] > 0


def test_referral_rating_is_counted(client: TestClient) -> None:
    _create_profile(client, 1, gender="male")
    _create_profile(client, 2, referral_telegram_id=1)

    response = client.get("/api/v1/users/1/rating")

    assert response.status_code == 200
    assert response.json()["referral_score"] > 0


def test_interactions_duplicate_guard_and_match(client: TestClient) -> None:
    _create_profile(client, 1, gender="male", gender_pref="any")
    _create_profile(client, 2, gender="female", gender_pref="any")

    first_like = client.post(
        "/api/v1/interactions",
        json={
            "requester_telegram_id": 1,
            "responder_telegram_id": 2,
            "is_like": True,
        },
    )
    assert first_like.status_code == 201
    assert first_like.json()["match"] is False

    duplicate = client.post(
        "/api/v1/interactions",
        json={
            "requester_telegram_id": 1,
            "responder_telegram_id": 2,
            "is_like": False,
        },
    )
    assert duplicate.status_code == 409

    reciprocal_like = client.post(
        "/api/v1/interactions",
        json={
            "requester_telegram_id": 2,
            "responder_telegram_id": 1,
            "is_like": True,
        },
    )
    assert reciprocal_like.status_code == 201
    assert reciprocal_like.json()["match"] is True

    rating = client.get("/api/v1/users/1/rating").json()
    assert rating["behavioral_score"] > 0


def test_interaction_publishes_mq_event(
    client: TestClient,
    event_publisher: InMemoryEventPublisher,
) -> None:
    _create_profile(client, 1, gender="male", gender_pref="any")
    _create_profile(client, 2, gender="female", gender_pref="any")

    response = client.post(
        "/api/v1/interactions",
        json={
            "requester_telegram_id": 1,
            "responder_telegram_id": 2,
            "is_like": True,
        },
    )

    assert response.status_code == 201
    events = event_publisher.snapshot()
    assert events[-1]["type"] == "InteractionCreated"
    assert events[-1]["payload"]["requester"] == 1
    assert events[-1]["payload"]["responder"] == 2


def test_feed_excludes_self_and_evaluated_profiles_and_sorts_by_rating(client: TestClient) -> None:
    _create_profile(client, 1, gender="male", gender_pref="any")
    _create_profile(client, 2, age=26, photos_count=4)
    _create_profile(client, 3, age=27, photos_count=0)

    first = client.get("/api/v1/feed/1/next")
    assert first.status_code == 200
    assert first.json()["profile"]["telegram_id"] == 2

    like = client.post(
        "/api/v1/interactions",
        json={
            "requester_telegram_id": 1,
            "responder_telegram_id": 2,
            "is_like": True,
        },
    )
    assert like.status_code == 201

    second = client.get("/api/v1/feed/1/next")
    assert second.status_code == 200
    assert second.json()["profile"]["telegram_id"] == 3


def test_feed_uses_cached_batch_between_requests(
    client: TestClient,
    candidate_cache: InMemoryCandidateCache,
    event_publisher: InMemoryEventPublisher,
) -> None:
    _create_profile(client, 1, gender="male", gender_pref="any")
    _create_profile(client, 2, photos_count=4)
    _create_profile(client, 3, photos_count=2)
    _create_profile(client, 4, photos_count=1)

    first = client.get("/api/v1/feed/1/next")
    assert first.status_code == 200

    cached_ids = candidate_cache.snapshot(1)
    assert cached_ids

    second = client.get("/api/v1/feed/1/next")
    assert second.status_code == 200
    assert second.json()["profile"]["telegram_id"] == cached_ids[0]

    feed_events = [
        event for event in event_publisher.snapshot() if event["type"] == "FeedRequested"
    ]
    assert feed_events

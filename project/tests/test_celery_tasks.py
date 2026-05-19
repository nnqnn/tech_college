from __future__ import annotations

from backend.storage import InMemoryDatingRepository


def test_celery_refresh_user_rating_task_uses_repository(
    monkeypatch,
    repository: InMemoryDatingRepository,
) -> None:
    from worker import celery_app as worker_tasks

    repository.upsert_profile(
        1,
        {
            "age": 28,
            "gender": "female",
            "city": "Moscow",
            "interests": "music",
            "age_pref_min": 18,
            "age_pref_max": 40,
            "gender_pref": "any",
            "city_pref": "any",
        },
    )
    monkeypatch.setattr(worker_tasks, "_repository", repository)

    result = worker_tasks.refresh_user_rating.run(1)

    assert result == {"telegram_id": 1, "refreshed": True}
    assert repository.get_rating(1) is not None


def test_celery_refresh_all_ratings_task_uses_repository(
    monkeypatch,
    repository: InMemoryDatingRepository,
) -> None:
    from worker import celery_app as worker_tasks

    repository.upsert_profile(1, {"age": 28, "gender": "female", "city": "Moscow"})
    repository.upsert_profile(2, {"age": 31, "gender": "male", "city": "Moscow"})
    monkeypatch.setattr(worker_tasks, "_repository", repository)

    result = worker_tasks.refresh_all_ratings.run()

    assert result == {"refreshed": 2}


def test_celery_process_interaction_event_refreshes_both_users(
    monkeypatch,
    repository: InMemoryDatingRepository,
) -> None:
    from worker import celery_app as worker_tasks

    repository.upsert_profile(1, {"age": 28, "gender": "female", "city": "Moscow"})
    repository.upsert_profile(2, {"age": 31, "gender": "male", "city": "Moscow"})
    monkeypatch.setattr(worker_tasks, "_repository", repository)

    result = worker_tasks.process_interaction_event.run({"requester": 1, "responder": 2})

    assert result == {"refreshed": 2}

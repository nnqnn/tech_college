from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, status

from backend.cache import CandidateCache, RedisCandidateCache
from backend.config import Settings, load_settings
from backend.events import EventPublisher, RabbitMQEventPublisher
from backend.schemas import (
    FeedProfileResponse,
    InteractionCreateRequest,
    InteractionResponse,
    ProfileResponse,
    ProfileUpsertRequest,
    RatingResponse,
    RegisterTelegramUserRequest,
    RegisterTelegramUserResponse,
    UserResponse,
)
from backend.storage import (
    DuplicateInteractionError,
    InvalidInteractionError,
    NotFoundError,
    PostgresDatingRepository,
)

logger = logging.getLogger(__name__)


def create_app(
    *,
    repository: Any,
    candidate_cache: CandidateCache,
    event_publisher: EventPublisher,
    settings: Settings,
    run_startup: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_startup:
            logger.info("Initializing backend storage")
            repository.initialize()
        app.state.repository = repository
        app.state.candidate_cache = candidate_cache
        app.state.event_publisher = event_publisher
        yield

    app = FastAPI(
        title="Dating Backend API",
        version="0.3.0",
        description="Backend API для регистрации, анкет, ранжирования и выдачи анкет.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/v1/users/register",
        response_model=RegisterTelegramUserResponse,
        status_code=status.HTTP_200_OK,
    )
    def register_user(payload: RegisterTelegramUserRequest) -> RegisterTelegramUserResponse:
        created, user = repository.upsert_user(
            telegram_id=payload.telegram_id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
        return RegisterTelegramUserResponse(created=created, user=_user_response(user))

    @app.get(
        "/api/v1/users/{telegram_id}",
        response_model=UserResponse,
        status_code=status.HTTP_200_OK,
    )
    def get_user(telegram_id: int) -> UserResponse:
        user = repository.get_user(telegram_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with telegram_id={telegram_id} not found",
            )
        return _user_response(user)

    @app.put(
        "/api/v1/profiles/{telegram_id}",
        response_model=ProfileResponse,
        status_code=status.HTTP_200_OK,
    )
    def upsert_profile(
        telegram_id: int,
        payload: ProfileUpsertRequest,
    ) -> ProfileResponse:
        _validate_age_range(payload.age_pref_min, payload.age_pref_max)
        profile = repository.upsert_profile(
            telegram_id,
            payload.model_dump(exclude_unset=True),
        )
        candidate_cache.clear(telegram_id)
        return _profile_response(profile)

    @app.get(
        "/api/v1/profiles/{telegram_id}",
        response_model=ProfileResponse,
        status_code=status.HTTP_200_OK,
    )
    def get_profile(telegram_id: int) -> ProfileResponse:
        user = repository.get_user(telegram_id)
        if user is None or user.age is None or user.gender is None or user.city is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with telegram_id={telegram_id} not found",
            )
        return _profile_response(user)

    @app.get(
        "/api/v1/profiles",
        response_model=list[ProfileResponse],
        status_code=status.HTTP_200_OK,
    )
    def list_profiles() -> list[ProfileResponse]:
        return [_profile_response(profile) for profile in repository.list_profiles()]

    @app.delete(
        "/api/v1/profiles/{telegram_id}",
        response_model=ProfileResponse,
        status_code=status.HTTP_200_OK,
    )
    def delete_profile(telegram_id: int) -> ProfileResponse:
        try:
            profile = repository.delete_profile(telegram_id)
        except NotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        candidate_cache.clear(telegram_id)
        return _profile_response(profile)

    @app.get(
        "/api/v1/feed/{telegram_id}/next",
        response_model=FeedProfileResponse,
        status_code=status.HTTP_200_OK,
    )
    def get_next_profile(telegram_id: int) -> FeedProfileResponse:
        for _ in range(settings.candidate_batch_size):
            candidate_id = candidate_cache.pop_candidate(telegram_id)
            if candidate_id is None:
                break
            if repository.is_feed_candidate(telegram_id, candidate_id):
                candidate = repository.get_user(candidate_id)
                rating = repository.get_rating(candidate_id)
                if candidate is not None and rating is not None:
                    _publish_event(
                        event_publisher,
                        "FeedRequested",
                        {
                            "requester": telegram_id,
                            "returned": candidate.telegram_id,
                            "source": "redis",
                        },
                    )
                    return FeedProfileResponse(
                        profile=_profile_response(candidate),
                        rating=_rating_response(rating),
                    )

        try:
            candidates = repository.list_feed_candidates(
                telegram_id,
                settings.candidate_batch_size,
            )
        except NotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except InvalidInteractionError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No profiles available for feed",
            )

        first_profile = candidates[0]
        remaining_ids = [candidate.telegram_id for candidate in candidates[1:]]
        candidate_cache.push_candidates(
            telegram_id,
            remaining_ids,
            settings.candidate_ttl_seconds,
        )
        rating = repository.get_rating(first_profile.telegram_id)
        if rating is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate rating not found",
            )
        logger.info(
            "FeedRequested requester=%s returned=%s cached=%s",
            telegram_id,
            first_profile.telegram_id,
            len(remaining_ids),
        )
        _publish_event(
            event_publisher,
            "FeedRequested",
            {
                "requester": telegram_id,
                "returned": first_profile.telegram_id,
                "source": "postgres",
                "cached": len(remaining_ids),
            },
        )
        return FeedProfileResponse(
            profile=_profile_response(first_profile),
            rating=_rating_response(rating),
        )

    @app.post(
        "/api/v1/interactions",
        response_model=InteractionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_interaction(payload: InteractionCreateRequest) -> InteractionResponse:
        try:
            interaction, is_match = repository.create_interaction(
                requester_telegram_id=payload.requester_telegram_id,
                responder_telegram_id=payload.responder_telegram_id,
                is_like=payload.is_like,
            )
        except DuplicateInteractionError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except NotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except InvalidInteractionError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

        candidate_cache.clear(payload.requester_telegram_id)
        logger.info(
            "InteractionCreated requester=%s responder=%s is_like=%s match=%s",
            payload.requester_telegram_id,
            payload.responder_telegram_id,
            payload.is_like,
            is_match,
        )
        _publish_event(
            event_publisher,
            "InteractionCreated",
            {
                "requester": interaction.requester_telegram_id,
                "responder": interaction.responder_telegram_id,
                "is_like": interaction.is_like,
                "match": is_match,
                "created_at": interaction.created_at.isoformat(),
            },
        )
        return InteractionResponse(
            requester_telegram_id=interaction.requester_telegram_id,
            responder_telegram_id=interaction.responder_telegram_id,
            is_like=interaction.is_like,
            match=is_match,
            created_at=interaction.created_at,
        )

    @app.get(
        "/api/v1/users/{telegram_id}/rating",
        response_model=RatingResponse,
        status_code=status.HTTP_200_OK,
    )
    def get_rating(telegram_id: int) -> RatingResponse:
        rating = repository.get_rating(telegram_id)
        if rating is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rating with telegram_id={telegram_id} not found",
            )
        return _rating_response(rating)

    return app


def _validate_age_range(age_pref_min: int | None, age_pref_max: int | None) -> None:
    if age_pref_min is not None and age_pref_max is not None and age_pref_min > age_pref_max:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="age_pref_min must be less than or equal to age_pref_max",
        )


def _user_response(user: Any) -> UserResponse:
    return UserResponse(**asdict(user))


def _profile_response(user: Any) -> ProfileResponse:
    return ProfileResponse(**asdict(user))


def _rating_response(rating: Any) -> RatingResponse:
    return RatingResponse(**asdict(rating))


def _publish_event(
    event_publisher: EventPublisher,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    event_publisher.publish(event_type, payload)


settings = load_settings()
repository = PostgresDatingRepository(settings.database_url)
candidate_cache = RedisCandidateCache(settings.redis_url)
event_publisher = RabbitMQEventPublisher(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=settings.event_queue_name,
    enabled=settings.mq_enabled,
)
app = create_app(
    repository=repository,
    candidate_cache=candidate_cache,
    event_publisher=event_publisher,
    settings=settings,
)

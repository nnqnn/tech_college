from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.cache import CandidateCache, RedisCandidateCache
from backend.config import Settings, load_settings
from backend.events import EventPublisher, RabbitMQEventPublisher
from backend.logging_config import configure_logging
from backend import metrics
from backend.object_storage import ObjectNotFoundError, ObjectStorage, S3ObjectStorage
from backend.rating_jobs import RatingTaskDispatcher
from backend.schemas import (
    FeedProfileResponse,
    InteractionCreateRequest,
    InteractionResponse,
    PhotoResponse,
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
    object_storage: ObjectStorage,
    rating_tasks: RatingTaskDispatcher,
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
        app.state.object_storage = object_storage
        app.state.rating_tasks = rating_tasks
        yield

    app = FastAPI(
        title="Dating Backend API",
        version="0.4.0",
        description="Backend API для регистрации, анкет, ранжирования и выдачи анкет.",
        lifespan=lifespan,
    )

    if settings.metrics_enabled:
        @app.middleware("http")
        async def collect_metrics(request, call_next):  # type: ignore[no-untyped-def]
            start = time.perf_counter()
            response = await call_next(request)
            path = request.scope.get("route").path if request.scope.get("route") else request.url.path
            elapsed = time.perf_counter() - start
            metrics.HTTP_REQUESTS.labels(
                method=request.method,
                path=path,
                status=str(response.status_code),
            ).inc()
            metrics.HTTP_LATENCY.labels(method=request.method, path=path).observe(elapsed)
            return response

    @app.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

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
        candidate_cache.clear()
        rating_tasks.refresh_user_rating(telegram_id)
        return _profile_response(repository, profile)

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
        return _profile_response(repository, user)

    @app.get(
        "/api/v1/profiles",
        response_model=list[ProfileResponse],
        status_code=status.HTTP_200_OK,
    )
    def list_profiles() -> list[ProfileResponse]:
        return [_profile_response(repository, profile) for profile in repository.list_profiles()]

    @app.delete(
        "/api/v1/profiles/{telegram_id}",
        response_model=ProfileResponse,
        status_code=status.HTTP_200_OK,
    )
    def delete_profile(telegram_id: int) -> ProfileResponse:
        photos = []
        try:
            photos = repository.list_photos(telegram_id)
            profile = repository.delete_profile(telegram_id)
        except NotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        for photo in photos:
            object_storage.delete_object(photo.s3_key)
        candidate_cache.clear()
        rating_tasks.refresh_user_rating(telegram_id)
        return _profile_response(repository, profile)

    @app.post(
        "/api/v1/profiles/{telegram_id}/photos",
        response_model=PhotoResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_profile_photo(telegram_id: int, file: UploadFile = File(...)) -> PhotoResponse:
        user = repository.get_user(telegram_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with telegram_id={telegram_id} not found",
            )

        photos = repository.list_photos(telegram_id)
        if len(photos) >= settings.max_profile_photos:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Profile can have at most {settings.max_profile_photos} photos",
            )

        content_type = file.content_type or "application/octet-stream"
        if not content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only image uploads are supported",
            )

        content = await file.read(settings.max_photo_size_bytes + 1)
        if len(content) > settings.max_photo_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Photo is too large",
            )

        photo_id = str(uuid4())
        s3_key = f"profiles/{telegram_id}/{photo_id}{_file_extension(file.filename, content_type)}"
        try:
            object_storage.put_object(s3_key, content, content_type)
            photo = repository.add_photo(
                photo_id=photo_id,
                telegram_id=telegram_id,
                s3_key=s3_key,
                content_type=content_type,
                file_size=len(content),
            )
        except NotFoundError as error:
            object_storage.delete_object(s3_key)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except Exception:
            object_storage.delete_object(s3_key)
            raise

        candidate_cache.clear()
        rating_tasks.refresh_user_rating(telegram_id)
        metrics.PHOTO_UPLOADS.inc()
        return _photo_response(photo)

    @app.get(
        "/api/v1/profiles/{telegram_id}/photos",
        response_model=list[PhotoResponse],
        status_code=status.HTTP_200_OK,
    )
    def list_profile_photos(telegram_id: int) -> list[PhotoResponse]:
        try:
            return [_photo_response(photo) for photo in repository.list_photos(telegram_id)]
        except NotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @app.get("/api/v1/photos/{photo_id}", status_code=status.HTTP_200_OK)
    def download_photo(photo_id: str) -> Response:
        photo = repository.get_photo(photo_id)
        if photo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Photo with id={photo_id} not found",
            )

        try:
            stored = object_storage.get_object(photo.s3_key)
        except ObjectNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

        return Response(content=stored.content, media_type=stored.content_type)

    @app.delete(
        "/api/v1/profiles/{telegram_id}/photos/{photo_id}",
        response_model=PhotoResponse,
        status_code=status.HTTP_200_OK,
    )
    def delete_profile_photo(telegram_id: int, photo_id: str) -> PhotoResponse:
        try:
            photo = repository.delete_photo(telegram_id, photo_id)
        except NotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

        object_storage.delete_object(photo.s3_key)
        candidate_cache.clear()
        rating_tasks.refresh_user_rating(telegram_id)
        metrics.PHOTO_DELETES.inc()
        return _photo_response(photo)

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
                    metrics.CACHE_HITS.inc()
                    metrics.FEED_REQUESTS.labels(source="redis").inc()
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
                        profile=_profile_response(repository, candidate),
                        rating=_rating_response(rating),
                    )
        metrics.CACHE_MISSES.inc()

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
        metrics.FEED_REQUESTS.labels(source="postgres").inc()
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
            profile=_profile_response(repository, first_profile),
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
        metrics.INTERACTIONS.labels(is_like=str(payload.is_like).lower()).inc()
        if is_match:
            metrics.MATCHES.inc()
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
        rating_tasks.process_interaction_event(
            {
                "requester": interaction.requester_telegram_id,
                "responder": interaction.responder_telegram_id,
                "is_like": interaction.is_like,
                "match": is_match,
            }
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


def _profile_response(repository: Any, user: Any) -> ProfileResponse:
    data = asdict(user)
    data["photos"] = [_photo_response(photo) for photo in repository.list_photos(user.telegram_id)]
    return ProfileResponse(**data)


def _rating_response(rating: Any) -> RatingResponse:
    return RatingResponse(**asdict(rating))


def _photo_response(photo: Any) -> PhotoResponse:
    data = asdict(photo)
    data.pop("s3_key", None)
    data["download_url"] = f"/api/v1/photos/{photo.id}"
    return PhotoResponse(**data)


def _file_extension(filename: str | None, content_type: str) -> str:
    if filename and "." in filename:
        suffix = filename.rsplit(".", 1)[1].strip().lower()
        if suffix and len(suffix) <= 8:
            return f".{suffix}"

    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type, ".img")


def _publish_event(
    event_publisher: EventPublisher,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    event_publisher.publish(event_type, payload)


settings = load_settings()
configure_logging(structured=settings.structured_logging)
repository = PostgresDatingRepository(settings.database_url)
candidate_cache = RedisCandidateCache(settings.redis_url)
event_publisher = RabbitMQEventPublisher(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=settings.event_queue_name,
    enabled=settings.mq_enabled,
)
object_storage = S3ObjectStorage(
    endpoint_url=settings.s3_endpoint_url,
    access_key_id=settings.s3_access_key_id,
    secret_access_key=settings.s3_secret_access_key,
    bucket_name=settings.s3_bucket_name,
    region_name=settings.s3_region_name,
)
rating_tasks = RatingTaskDispatcher(settings=settings, repository=repository)
app = create_app(
    repository=repository,
    candidate_cache=candidate_cache,
    event_publisher=event_publisher,
    object_storage=object_storage,
    rating_tasks=rating_tasks,
    settings=settings,
)

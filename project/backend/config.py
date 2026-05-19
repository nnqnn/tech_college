from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    rabbitmq_url: str
    event_queue_name: str
    mq_enabled: bool
    celery_broker_url: str
    celery_result_backend: str
    celery_enabled: bool
    rating_refresh_interval_seconds: int
    candidate_batch_size: int
    candidate_ttl_seconds: int
    s3_endpoint_url: str | None
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket_name: str
    s3_region_name: str
    max_profile_photos: int
    max_photo_size_bytes: int
    metrics_enabled: bool
    worker_metrics_port: int
    structured_logging: bool


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _load_dotenv_if_exists() -> None:
    project_root = Path(__file__).resolve().parents[1]
    candidate_paths = (Path.cwd() / ".env", project_root / ".env")

    for env_path in candidate_paths:
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = _strip_quotes(value.strip())
            if key:
                os.environ.setdefault(key, value)


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error

    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    _load_dotenv_if_exists()

    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://dating:dating@localhost:5432/dating",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://dating:dating@localhost:5672/"),
        event_queue_name=os.getenv("EVENT_QUEUE_NAME", "dating.events"),
        mq_enabled=_read_bool("MQ_ENABLED", True),
        celery_broker_url=os.getenv(
            "CELERY_BROKER_URL",
            os.getenv("RABBITMQ_URL", "amqp://dating:dating@localhost:5672/"),
        ),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        celery_enabled=_read_bool("CELERY_ENABLED", True),
        rating_refresh_interval_seconds=_read_positive_int(
            "RATING_REFRESH_INTERVAL_SECONDS",
            300,
        ),
        candidate_batch_size=_read_positive_int("CANDIDATE_BATCH_SIZE", 10),
        candidate_ttl_seconds=_read_positive_int("CANDIDATE_TTL_SECONDS", 900),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000") or None,
        s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID", "dating"),
        s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", "dating-secret"),
        s3_bucket_name=os.getenv("S3_BUCKET_NAME", "dating-photos"),
        s3_region_name=os.getenv("S3_REGION_NAME", "us-east-1"),
        max_profile_photos=_read_positive_int("MAX_PROFILE_PHOTOS", 4),
        max_photo_size_bytes=_read_positive_int("MAX_PHOTO_SIZE_BYTES", 5 * 1024 * 1024),
        metrics_enabled=_read_bool("METRICS_ENABLED", True),
        worker_metrics_port=_read_positive_int("WORKER_METRICS_PORT", 9101),
        structured_logging=_read_bool("STRUCTURED_LOGGING", True),
    )

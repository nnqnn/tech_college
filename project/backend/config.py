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
    candidate_batch_size: int
    candidate_ttl_seconds: int


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
        candidate_batch_size=_read_positive_int("CANDIDATE_BATCH_SIZE", 10),
        candidate_ttl_seconds=_read_positive_int("CANDIDATE_TTL_SECONDS", 900),
    )

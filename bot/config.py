from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    backend_api_url: str


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


def load_settings() -> Settings:
    _load_dotenv_if_exists()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    backend_api_url = os.getenv("BACKEND_API_URL", "http://localhost:8000").rstrip("/")
    return Settings(
        telegram_bot_token=telegram_bot_token,
        backend_api_url=backend_api_url,
    )

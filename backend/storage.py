from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass(slots=True)
class UserRecord:
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    created_at: datetime
    updated_at: datetime


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, UserRecord] = {}
        self._lock = Lock()

    def upsert_user(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> tuple[bool, UserRecord]:
        with self._lock:
            now = datetime.now(tz=timezone.utc)
            existing = self._users.get(telegram_id)
            if existing is None:
                user = UserRecord(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    created_at=now,
                    updated_at=now,
                )
                self._users[telegram_id] = user
                return True, user

            existing.username = username or existing.username
            existing.first_name = first_name or existing.first_name
            existing.last_name = last_name or existing.last_name
            existing.updated_at = now
            return False, existing

    def get_user(self, telegram_id: int) -> UserRecord | None:
        with self._lock:
            return self._users.get(telegram_id)

    def clear(self) -> None:
        with self._lock:
            self._users.clear()

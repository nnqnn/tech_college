from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RegistrationResult:
    created: bool
    telegram_id: int


class BackendClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def register_user(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> RegistrationResult:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            response = await client.post("/api/v1/users/register", json=payload)
            response.raise_for_status()
            data = response.json()

        return RegistrationResult(
            created=bool(data["created"]),
            telegram_id=int(data["user"]["telegram_id"]),
        )

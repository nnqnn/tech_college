from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RegistrationResult:
    created: bool
    telegram_id: int


@dataclass(frozen=True)
class ProfileResult:
    telegram_id: int
    age: int | None
    gender: str | None
    interests: str | None
    city: str | None
    profile_completion_pct: int
    photos_count: int
    total_score: float | None = None


@dataclass(frozen=True)
class InteractionResult:
    match: bool


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

    async def upsert_profile(self, telegram_id: int, payload: dict[str, object]) -> ProfileResult:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            response = await client.put(f"/api/v1/profiles/{telegram_id}", json=payload)
            response.raise_for_status()
            data = response.json()
        return _profile_from_payload(data)

    async def get_profile(self, telegram_id: int) -> ProfileResult | None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            response = await client.get(f"/api/v1/profiles/{telegram_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
        return _profile_from_payload(data)

    async def delete_profile(self, telegram_id: int) -> ProfileResult:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            response = await client.delete(f"/api/v1/profiles/{telegram_id}")
            response.raise_for_status()
            data = response.json()
        return _profile_from_payload(data)

    async def get_next_profile(self, telegram_id: int) -> ProfileResult | None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            response = await client.get(f"/api/v1/feed/{telegram_id}/next")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

        profile = _profile_from_payload(data["profile"])
        return ProfileResult(
            telegram_id=profile.telegram_id,
            age=profile.age,
            gender=profile.gender,
            interests=profile.interests,
            city=profile.city,
            profile_completion_pct=profile.profile_completion_pct,
            photos_count=profile.photos_count,
            total_score=float(data["rating"]["total_score"]),
        )

    async def create_interaction(
        self,
        *,
        requester_telegram_id: int,
        responder_telegram_id: int,
        is_like: bool,
    ) -> InteractionResult:
        payload = {
            "requester_telegram_id": requester_telegram_id,
            "responder_telegram_id": responder_telegram_id,
            "is_like": is_like,
        }
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            response = await client.post("/api/v1/interactions", json=payload)
            response.raise_for_status()
            data = response.json()
        return InteractionResult(match=bool(data["match"]))


def _profile_from_payload(data: dict[str, object]) -> ProfileResult:
    return ProfileResult(
        telegram_id=int(data["telegram_id"]),
        age=data["age"] if data["age"] is None else int(data["age"]),
        gender=data["gender"],
        interests=data["interests"],
        city=data["city"],
        profile_completion_pct=int(data["profile_completion_pct"]),
        photos_count=int(data["photos_count"]),
    )

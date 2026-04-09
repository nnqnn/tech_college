from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, status

from backend.schemas import (
    RegisterTelegramUserRequest,
    RegisterTelegramUserResponse,
    UserResponse,
)
from backend.storage import InMemoryUserRepository

app = FastAPI(
    title="Dating Backend API",
    version="0.1.0",
    description="Минимальный backend для регистрации пользователя из Telegram.",
)

# Временное хранилище для базового прототипа.
repository = InMemoryUserRepository()


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
    return RegisterTelegramUserResponse(created=created, user=UserResponse(**asdict(user)))


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
    return UserResponse(**asdict(user))

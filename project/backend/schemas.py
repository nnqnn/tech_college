from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterTelegramUserRequest(BaseModel):
    telegram_id: int = Field(..., gt=0)
    username: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)


class UserResponse(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    created_at: datetime
    updated_at: datetime


class RegisterTelegramUserResponse(BaseModel):
    created: bool
    user: UserResponse

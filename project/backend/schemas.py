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
    age: int | None = None
    gender: str | None = None
    interests: str | None = None
    city: str | None = None
    profile_completion_pct: int = 0
    photos_count: int = 0
    age_pref_min: int | None = None
    age_pref_max: int | None = None
    gender_pref: str | None = None
    city_pref: str | None = None
    interests_pref: str | None = None
    last_activity: datetime | None = None
    referral_telegram_id: int | None = None
    created_at: datetime
    updated_at: datetime


class RegisterTelegramUserResponse(BaseModel):
    created: bool
    user: UserResponse


class ProfileUpsertRequest(BaseModel):
    age: int | None = Field(default=None, ge=18, le=120)
    gender: str | None = Field(default=None, max_length=32)
    interests: str | None = Field(default=None, max_length=1000)
    city: str | None = Field(default=None, max_length=128)
    age_pref_min: int | None = Field(default=None, ge=18, le=120)
    age_pref_max: int | None = Field(default=None, ge=18, le=120)
    gender_pref: str | None = Field(default=None, max_length=32)
    city_pref: str | None = Field(default=None, max_length=128)
    interests_pref: str | None = Field(default=None, max_length=1000)
    photos_count: int | None = Field(default=None, ge=0, le=20)
    referral_telegram_id: int | None = Field(default=None, gt=0)


class ProfileResponse(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    age: int | None = None
    gender: str | None = None
    interests: str | None = None
    city: str | None = None
    profile_completion_pct: int
    photos_count: int
    age_pref_min: int | None = None
    age_pref_max: int | None = None
    gender_pref: str | None = None
    city_pref: str | None = None
    interests_pref: str | None = None
    referral_telegram_id: int | None = None
    updated_at: datetime


class RatingResponse(BaseModel):
    telegram_id: int
    primary_score: float
    behavioral_score: float
    referral_score: float
    total_score: float
    calculated_at: datetime


class FeedProfileResponse(BaseModel):
    profile: ProfileResponse
    rating: RatingResponse


class InteractionCreateRequest(BaseModel):
    requester_telegram_id: int = Field(..., gt=0)
    responder_telegram_id: int = Field(..., gt=0)
    is_like: bool


class InteractionResponse(BaseModel):
    requester_telegram_id: int
    responder_telegram_id: int
    is_like: bool
    match: bool
    created_at: datetime

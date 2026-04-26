from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class InteractionStats:
    received_likes: int = 0
    received_skips: int = 0
    mutual_likes: int = 0
    referrals_count: int = 0


@dataclass(frozen=True)
class ScoreBreakdown:
    primary_score: float
    behavioral_score: float
    referral_score: float
    total_score: float


PROFILE_FIELDS = (
    "age",
    "gender",
    "interests",
    "city",
    "age_pref_min",
    "age_pref_max",
    "gender_pref",
    "city_pref",
    "interests_pref",
    "photos_count",
)


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, int):
        return value > 0
    return True


def calculate_profile_completion(profile: dict[str, object]) -> int:
    filled = sum(1 for field in PROFILE_FIELDS if _has_value(profile.get(field)))
    return round(filled / len(PROFILE_FIELDS) * 100)


def calculate_scores(
    *,
    profile_completion_pct: int,
    age: int | None,
    gender: str | None,
    interests: str | None,
    city: str | None,
    age_pref_min: int | None,
    age_pref_max: int | None,
    gender_pref: str | None,
    city_pref: str | None,
    interests_pref: str | None,
    photos_count: int,
    last_activity: datetime | None,
    stats: InteractionStats,
) -> ScoreBreakdown:
    main_fields = (age, gender, interests, city)
    preference_fields = (
        age_pref_min,
        age_pref_max,
        gender_pref,
        city_pref,
        interests_pref,
    )

    main_score = sum(1 for value in main_fields if _has_value(value)) / len(main_fields) * 10
    preference_score = (
        sum(1 for value in preference_fields if _has_value(value)) / len(preference_fields) * 10
    )
    photo_score = min(photos_count, 4) / 4 * 20
    primary_score = min(
        100.0,
        profile_completion_pct * 0.60 + main_score + preference_score + photo_score,
    )

    received_total = stats.received_likes + stats.received_skips
    like_ratio = stats.received_likes / received_total if received_total else 0.0
    activity_score = _activity_score(last_activity)
    behavioral_score = min(
        100.0,
        min(stats.received_likes, 20) * 2
        + like_ratio * 35
        + min(stats.mutual_likes, 10) * 3
        + activity_score,
    )

    referral_score = min(100.0, stats.referrals_count * 20.0)
    total_score = primary_score * 0.55 + behavioral_score * 0.35 + referral_score * 0.10

    return ScoreBreakdown(
        primary_score=round(primary_score, 2),
        behavioral_score=round(behavioral_score, 2),
        referral_score=round(referral_score, 2),
        total_score=round(total_score, 2),
    )


def _activity_score(last_activity: datetime | None) -> float:
    if last_activity is None:
        return 0.0

    now = datetime.now(timezone.utc)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)
    hours_since_activity = (now - last_activity).total_seconds() / 3600

    if hours_since_activity <= 24:
        return 20.0
    if hours_since_activity <= 24 * 7:
        return 10.0
    return 0.0

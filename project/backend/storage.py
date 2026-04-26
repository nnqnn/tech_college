from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.ranking import (
    InteractionStats,
    calculate_profile_completion,
    calculate_scores,
)


class DuplicateInteractionError(Exception):
    pass


class InvalidInteractionError(Exception):
    pass


class NotFoundError(Exception):
    pass


@dataclass(slots=True)
class UserRecord:
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    age: int | None
    gender: str | None
    interests: str | None
    city: str | None
    profile_completion_pct: int
    photos_count: int
    age_pref_min: int | None
    age_pref_max: int | None
    gender_pref: str | None
    city_pref: str | None
    interests_pref: str | None
    last_activity: datetime | None
    referral_telegram_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RatingRecord:
    telegram_id: int
    primary_score: float
    behavioral_score: float
    referral_score: float
    total_score: float
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class InteractionRecord:
    id: str
    requester_telegram_id: int
    responder_telegram_id: int
    is_like: bool
    created_at: datetime


PROFILE_COLUMNS = (
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
    "referral_telegram_id",
)


ANY_VALUES = {"any", "all", "любой", "любая", "все", "неважно", "нет"}


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _profile_dict(user: UserRecord, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    data = {
        "age": user.age,
        "gender": user.gender,
        "interests": user.interests,
        "city": user.city,
        "age_pref_min": user.age_pref_min,
        "age_pref_max": user.age_pref_max,
        "gender_pref": user.gender_pref,
        "city_pref": user.city_pref,
        "interests_pref": user.interests_pref,
        "photos_count": user.photos_count,
        "referral_telegram_id": user.referral_telegram_id,
    }
    if updates:
        data.update(updates)
    return data


def _normalise_profile_updates(updates: dict[str, Any]) -> dict[str, Any]:
    normalised = dict(updates)
    for key in ("gender", "interests", "city", "gender_pref", "city_pref", "interests_pref"):
        if key in normalised:
            normalised[key] = _clean_text(normalised[key])

    if "photos_count" in normalised and normalised["photos_count"] is None:
        normalised["photos_count"] = 0

    return normalised


def _profile_is_visible(user: UserRecord) -> bool:
    return user.age is not None and bool(user.gender) and bool(user.city)


def _is_any_preference(value: str | None) -> bool:
    return value is None or value.strip().lower() in ANY_VALUES


def _split_interest_tokens(value: str | None) -> set[str]:
    if not value:
        return set()

    raw_tokens = value.replace(",", " ").replace(";", " ").split()
    return {token.strip().lower() for token in raw_tokens if token.strip()}


def _matches_preferences(requester: UserRecord, candidate: UserRecord) -> bool:
    if not _profile_is_visible(candidate):
        return False

    if requester.age_pref_min is not None and (
        candidate.age is None or candidate.age < requester.age_pref_min
    ):
        return False
    if requester.age_pref_max is not None and (
        candidate.age is None or candidate.age > requester.age_pref_max
    ):
        return False
    if not _is_any_preference(requester.gender_pref):
        if (candidate.gender or "").strip().lower() != requester.gender_pref.strip().lower():
            return False
    if not _is_any_preference(requester.city_pref):
        if (candidate.city or "").strip().lower() != requester.city_pref.strip().lower():
            return False

    preferred_interests = _split_interest_tokens(requester.interests_pref)
    if preferred_interests:
        candidate_interests = _split_interest_tokens(candidate.interests)
        if candidate_interests and preferred_interests.isdisjoint(candidate_interests):
            return False

    return True


def _build_rating(user: UserRecord, stats: InteractionStats) -> RatingRecord:
    scores = calculate_scores(
        profile_completion_pct=user.profile_completion_pct,
        age=user.age,
        gender=user.gender,
        interests=user.interests,
        city=user.city,
        age_pref_min=user.age_pref_min,
        age_pref_max=user.age_pref_max,
        gender_pref=user.gender_pref,
        city_pref=user.city_pref,
        interests_pref=user.interests_pref,
        photos_count=user.photos_count,
        last_activity=user.last_activity,
        stats=stats,
    )
    return RatingRecord(
        telegram_id=user.telegram_id,
        primary_score=scores.primary_score,
        behavioral_score=scores.behavioral_score,
        referral_score=scores.referral_score,
        total_score=scores.total_score,
        calculated_at=_utc_now(),
    )


class InMemoryDatingRepository:
    def __init__(self) -> None:
        self._users: dict[int, UserRecord] = {}
        self._interactions: dict[tuple[int, int], InteractionRecord] = {}
        self._ratings: dict[int, RatingRecord] = {}
        self._lock = Lock()

    def initialize(self) -> None:
        return

    def upsert_user(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> tuple[bool, UserRecord]:
        with self._lock:
            now = _utc_now()
            existing = self._users.get(telegram_id)
            if existing is None:
                user = UserRecord(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    age=None,
                    gender=None,
                    interests=None,
                    city=None,
                    profile_completion_pct=0,
                    photos_count=0,
                    age_pref_min=None,
                    age_pref_max=None,
                    gender_pref=None,
                    city_pref=None,
                    interests_pref=None,
                    last_activity=now,
                    referral_telegram_id=None,
                    created_at=now,
                    updated_at=now,
                )
                self._users[telegram_id] = user
                self._ratings[telegram_id] = _build_rating(user, self._interaction_stats(telegram_id))
                return True, user

            existing.username = username or existing.username
            existing.first_name = first_name or existing.first_name
            existing.last_name = last_name or existing.last_name
            existing.last_activity = now
            existing.updated_at = now
            self._ratings[telegram_id] = _build_rating(existing, self._interaction_stats(telegram_id))
            return False, existing

    def get_user(self, telegram_id: int) -> UserRecord | None:
        with self._lock:
            return self._users.get(telegram_id)

    def upsert_profile(self, telegram_id: int, updates: dict[str, Any]) -> UserRecord:
        updates = _normalise_profile_updates(updates)
        with self._lock:
            user = self._users.get(telegram_id)
            if user is None:
                _, user = self._upsert_user_unlocked(
                    telegram_id=telegram_id,
                    username=None,
                    first_name=None,
                    last_name=None,
                )

            referral_id = updates.get("referral_telegram_id")
            if referral_id is not None and referral_id not in self._users:
                self._upsert_user_unlocked(
                    telegram_id=referral_id,
                    username=None,
                    first_name=None,
                    last_name=None,
                )

            data = _profile_dict(user, updates)
            data["profile_completion_pct"] = calculate_profile_completion(data)
            for key, value in data.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            user.profile_completion_pct = data["profile_completion_pct"]
            user.last_activity = _utc_now()
            user.updated_at = user.last_activity
            self._refresh_rating_unlocked(telegram_id)
            if user.referral_telegram_id is not None:
                self._refresh_rating_unlocked(user.referral_telegram_id)
            return user

    def _upsert_user_unlocked(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> tuple[bool, UserRecord]:
        now = _utc_now()
        user = UserRecord(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            age=None,
            gender=None,
            interests=None,
            city=None,
            profile_completion_pct=0,
            photos_count=0,
            age_pref_min=None,
            age_pref_max=None,
            gender_pref=None,
            city_pref=None,
            interests_pref=None,
            last_activity=now,
            referral_telegram_id=None,
            created_at=now,
            updated_at=now,
        )
        self._users[telegram_id] = user
        self._ratings[telegram_id] = _build_rating(user, self._interaction_stats(telegram_id))
        return True, user

    def delete_profile(self, telegram_id: int) -> UserRecord:
        with self._lock:
            user = self._users.get(telegram_id)
            if user is None:
                raise NotFoundError(f"User with telegram_id={telegram_id} not found")

            old_referral_id = user.referral_telegram_id
            user.age = None
            user.gender = None
            user.interests = None
            user.city = None
            user.profile_completion_pct = 0
            user.photos_count = 0
            user.age_pref_min = None
            user.age_pref_max = None
            user.gender_pref = None
            user.city_pref = None
            user.interests_pref = None
            user.referral_telegram_id = None
            user.last_activity = _utc_now()
            user.updated_at = user.last_activity
            self._refresh_rating_unlocked(telegram_id)
            if old_referral_id is not None:
                self._refresh_rating_unlocked(old_referral_id)
            return user

    def list_profiles(self) -> list[UserRecord]:
        with self._lock:
            return sorted(
                [user for user in self._users.values() if _profile_is_visible(user)],
                key=lambda user: user.telegram_id,
            )

    def create_interaction(
        self,
        *,
        requester_telegram_id: int,
        responder_telegram_id: int,
        is_like: bool,
    ) -> tuple[InteractionRecord, bool]:
        with self._lock:
            if requester_telegram_id == responder_telegram_id:
                raise InvalidInteractionError("User cannot interact with own profile")
            if requester_telegram_id not in self._users:
                raise NotFoundError(f"User with telegram_id={requester_telegram_id} not found")
            if responder_telegram_id not in self._users:
                raise NotFoundError(f"User with telegram_id={responder_telegram_id} not found")

            key = (requester_telegram_id, responder_telegram_id)
            if key in self._interactions:
                raise DuplicateInteractionError("Interaction already exists")

            now = _utc_now()
            interaction = InteractionRecord(
                id=str(uuid4()),
                requester_telegram_id=requester_telegram_id,
                responder_telegram_id=responder_telegram_id,
                is_like=is_like,
                created_at=now,
            )
            self._interactions[key] = interaction
            self._users[requester_telegram_id].last_activity = now
            self._users[requester_telegram_id].updated_at = now
            match = is_like and self._has_like_unlocked(responder_telegram_id, requester_telegram_id)
            self._refresh_rating_unlocked(requester_telegram_id)
            self._refresh_rating_unlocked(responder_telegram_id)
            return interaction, match

    def get_rating(self, telegram_id: int) -> RatingRecord | None:
        with self._lock:
            if telegram_id not in self._users:
                return None
            rating = self._ratings.get(telegram_id)
            if rating is None:
                rating = self._refresh_rating_unlocked(telegram_id)
            return rating

    def refresh_rating(self, telegram_id: int) -> RatingRecord | None:
        with self._lock:
            return self._refresh_rating_unlocked(telegram_id)

    def list_feed_candidates(self, telegram_id: int, limit: int) -> list[UserRecord]:
        with self._lock:
            requester = self._users.get(telegram_id)
            if requester is None:
                raise NotFoundError(f"User with telegram_id={telegram_id} not found")
            if not _profile_is_visible(requester):
                raise InvalidInteractionError("Create a profile before requesting feed")

            candidates = [
                candidate
                for candidate in self._users.values()
                if self._is_feed_candidate_unlocked(requester, candidate)
            ]
            candidates.sort(
                key=lambda user: self._ratings.get(user.telegram_id, self._refresh_rating_unlocked(user.telegram_id)).total_score,
                reverse=True,
            )
            return candidates[:limit]

    def is_feed_candidate(self, requester_telegram_id: int, candidate_telegram_id: int) -> bool:
        with self._lock:
            requester = self._users.get(requester_telegram_id)
            candidate = self._users.get(candidate_telegram_id)
            if requester is None or candidate is None:
                return False
            return self._is_feed_candidate_unlocked(requester, candidate)

    def clear(self) -> None:
        with self._lock:
            self._users.clear()
            self._interactions.clear()
            self._ratings.clear()

    def _is_feed_candidate_unlocked(self, requester: UserRecord, candidate: UserRecord) -> bool:
        return (
            requester.telegram_id != candidate.telegram_id
            and (requester.telegram_id, candidate.telegram_id) not in self._interactions
            and _matches_preferences(requester, candidate)
        )

    def _has_like_unlocked(self, requester_telegram_id: int, responder_telegram_id: int) -> bool:
        interaction = self._interactions.get((requester_telegram_id, responder_telegram_id))
        return bool(interaction and interaction.is_like)

    def _interaction_stats(self, telegram_id: int) -> InteractionStats:
        received = [
            interaction
            for interaction in self._interactions.values()
            if interaction.responder_telegram_id == telegram_id
        ]
        received_likes = sum(1 for interaction in received if interaction.is_like)
        received_skips = sum(1 for interaction in received if not interaction.is_like)
        mutual_likes = sum(
            1
            for interaction in received
            if interaction.is_like and self._has_like_unlocked(telegram_id, interaction.requester_telegram_id)
        )
        referrals_count = sum(
            1 for user in self._users.values() if user.referral_telegram_id == telegram_id
        )
        return InteractionStats(
            received_likes=received_likes,
            received_skips=received_skips,
            mutual_likes=mutual_likes,
            referrals_count=referrals_count,
        )

    def _refresh_rating_unlocked(self, telegram_id: int) -> RatingRecord | None:
        user = self._users.get(telegram_id)
        if user is None:
            return None
        rating = _build_rating(user, self._interaction_stats(telegram_id))
        self._ratings[telegram_id] = rating
        return rating


class PostgresDatingRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    username VARCHAR(64),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    age INT,
                    gender VARCHAR(32),
                    interests TEXT,
                    city VARCHAR(128),
                    profile_completion_pct INT NOT NULL DEFAULT 0,
                    photos_count INT NOT NULL DEFAULT 0,
                    age_pref_min INT,
                    age_pref_max INT,
                    gender_pref VARCHAR(32),
                    city_pref VARCHAR(128),
                    interests_pref TEXT,
                    last_activity TIMESTAMPTZ,
                    referral_telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_photos (
                    id UUID PRIMARY KEY,
                    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    s3_key VARCHAR(512) NOT NULL,
                    sort_order INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_interactions (
                    id UUID PRIMARY KEY,
                    requester_telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    responder_telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    is_like BOOLEAN NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT user_interactions_unique_pair
                        UNIQUE (requester_telegram_id, responder_telegram_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_ratings (
                    telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
                    primary_score DOUBLE PRECISION NOT NULL,
                    behavioral_score DOUBLE PRECISION NOT NULL,
                    referral_score DOUBLE PRECISION NOT NULL,
                    total_score DOUBLE PRECISION NOT NULL,
                    calculated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_city_gender_age ON users (city, gender, age)"
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_requester_created
                ON user_interactions (requester_telegram_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_responder_created
                ON user_interactions (responder_telegram_id, created_at)
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_ratings_total_score ON user_ratings (total_score)"
            )

    def upsert_user(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> tuple[bool, UserRecord]:
        created = self.get_user(telegram_id) is None
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO users (
                    telegram_id, username, first_name, last_name, last_activity, created_at, updated_at
                )
                VALUES (
                    %(telegram_id)s, %(username)s, %(first_name)s, %(last_name)s,
                    %(now)s, %(now)s, %(now)s
                )
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = COALESCE(EXCLUDED.username, users.username),
                    first_name = COALESCE(EXCLUDED.first_name, users.first_name),
                    last_name = COALESCE(EXCLUDED.last_name, users.last_name),
                    last_activity = EXCLUDED.last_activity,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                {
                    "telegram_id": telegram_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "now": _utc_now(),
                },
            ).fetchone()

        user = self._row_to_user(row)
        self.refresh_rating(telegram_id)
        return created, user

    def get_user(self, telegram_id: int) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id = %(telegram_id)s",
                {"telegram_id": telegram_id},
            ).fetchone()
        return self._row_to_user(row) if row else None

    def upsert_profile(self, telegram_id: int, updates: dict[str, Any]) -> UserRecord:
        updates = _normalise_profile_updates(updates)
        if self.get_user(telegram_id) is None:
            self.upsert_user(
                telegram_id=telegram_id,
                username=None,
                first_name=None,
                last_name=None,
            )

        referral_id = updates.get("referral_telegram_id")
        if referral_id is not None and self.get_user(referral_id) is None:
            self.upsert_user(
                telegram_id=referral_id,
                username=None,
                first_name=None,
                last_name=None,
            )

        current = self.get_user(telegram_id)
        if current is None:
            raise NotFoundError(f"User with telegram_id={telegram_id} not found")

        data = _profile_dict(current, updates)
        completion_pct = calculate_profile_completion(data)
        data["profile_completion_pct"] = completion_pct
        data["telegram_id"] = telegram_id
        data["now"] = _utc_now()

        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE users SET
                    age = %(age)s,
                    gender = %(gender)s,
                    interests = %(interests)s,
                    city = %(city)s,
                    profile_completion_pct = %(profile_completion_pct)s,
                    photos_count = %(photos_count)s,
                    age_pref_min = %(age_pref_min)s,
                    age_pref_max = %(age_pref_max)s,
                    gender_pref = %(gender_pref)s,
                    city_pref = %(city_pref)s,
                    interests_pref = %(interests_pref)s,
                    referral_telegram_id = %(referral_telegram_id)s,
                    last_activity = %(now)s,
                    updated_at = %(now)s
                WHERE telegram_id = %(telegram_id)s
                RETURNING *
                """,
                data,
            ).fetchone()

        user = self._row_to_user(row)
        self.refresh_rating(telegram_id)
        if user.referral_telegram_id is not None:
            self.refresh_rating(user.referral_telegram_id)
        return user

    def delete_profile(self, telegram_id: int) -> UserRecord:
        current = self.get_user(telegram_id)
        if current is None:
            raise NotFoundError(f"User with telegram_id={telegram_id} not found")

        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE users SET
                    age = NULL,
                    gender = NULL,
                    interests = NULL,
                    city = NULL,
                    profile_completion_pct = 0,
                    photos_count = 0,
                    age_pref_min = NULL,
                    age_pref_max = NULL,
                    gender_pref = NULL,
                    city_pref = NULL,
                    interests_pref = NULL,
                    referral_telegram_id = NULL,
                    last_activity = %(now)s,
                    updated_at = %(now)s
                WHERE telegram_id = %(telegram_id)s
                RETURNING *
                """,
                {"telegram_id": telegram_id, "now": _utc_now()},
            ).fetchone()

        user = self._row_to_user(row)
        self.refresh_rating(telegram_id)
        if current.referral_telegram_id is not None:
            self.refresh_rating(current.referral_telegram_id)
        return user

    def list_profiles(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM users
                WHERE age IS NOT NULL AND gender IS NOT NULL AND city IS NOT NULL
                ORDER BY telegram_id
                """
            ).fetchall()
        return [self._row_to_user(row) for row in rows]

    def create_interaction(
        self,
        *,
        requester_telegram_id: int,
        responder_telegram_id: int,
        is_like: bool,
    ) -> tuple[InteractionRecord, bool]:
        if requester_telegram_id == responder_telegram_id:
            raise InvalidInteractionError("User cannot interact with own profile")
        if self.get_user(requester_telegram_id) is None:
            raise NotFoundError(f"User with telegram_id={requester_telegram_id} not found")
        if self.get_user(responder_telegram_id) is None:
            raise NotFoundError(f"User with telegram_id={responder_telegram_id} not found")

        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    INSERT INTO user_interactions (
                        id, requester_telegram_id, responder_telegram_id, is_like, created_at
                    )
                    VALUES (%(id)s, %(requester)s, %(responder)s, %(is_like)s, %(now)s)
                    RETURNING *
                    """,
                    {
                        "id": str(uuid4()),
                        "requester": requester_telegram_id,
                        "responder": responder_telegram_id,
                        "is_like": is_like,
                        "now": _utc_now(),
                    },
                ).fetchone()
                conn.execute(
                    """
                    UPDATE users SET last_activity = %(now)s, updated_at = %(now)s
                    WHERE telegram_id = %(telegram_id)s
                    """,
                    {"telegram_id": requester_telegram_id, "now": row["created_at"]},
                )
        except self._unique_violation_error():
            raise DuplicateInteractionError("Interaction already exists") from None

        interaction = self._row_to_interaction(row)
        match = is_like and self._has_like(
            requester_telegram_id=responder_telegram_id,
            responder_telegram_id=requester_telegram_id,
        )
        self.refresh_rating(requester_telegram_id)
        self.refresh_rating(responder_telegram_id)
        return interaction, match

    def get_rating(self, telegram_id: int) -> RatingRecord | None:
        if self.get_user(telegram_id) is None:
            return None

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_ratings WHERE telegram_id = %(telegram_id)s",
                {"telegram_id": telegram_id},
            ).fetchone()
        if row:
            return self._row_to_rating(row)
        return self.refresh_rating(telegram_id)

    def refresh_rating(self, telegram_id: int) -> RatingRecord | None:
        user = self.get_user(telegram_id)
        if user is None:
            return None

        rating = _build_rating(user, self._interaction_stats(telegram_id))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_ratings (
                    telegram_id, primary_score, behavioral_score,
                    referral_score, total_score, calculated_at
                )
                VALUES (
                    %(telegram_id)s, %(primary_score)s, %(behavioral_score)s,
                    %(referral_score)s, %(total_score)s, %(calculated_at)s
                )
                ON CONFLICT (telegram_id) DO UPDATE SET
                    primary_score = EXCLUDED.primary_score,
                    behavioral_score = EXCLUDED.behavioral_score,
                    referral_score = EXCLUDED.referral_score,
                    total_score = EXCLUDED.total_score,
                    calculated_at = EXCLUDED.calculated_at
                """,
                {
                    "telegram_id": rating.telegram_id,
                    "primary_score": rating.primary_score,
                    "behavioral_score": rating.behavioral_score,
                    "referral_score": rating.referral_score,
                    "total_score": rating.total_score,
                    "calculated_at": rating.calculated_at,
                },
            )
        return rating

    def list_feed_candidates(self, telegram_id: int, limit: int) -> list[UserRecord]:
        requester = self.get_user(telegram_id)
        if requester is None:
            raise NotFoundError(f"User with telegram_id={telegram_id} not found")
        if not _profile_is_visible(requester):
            raise InvalidInteractionError("Create a profile before requesting feed")

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT users.*, COALESCE(user_ratings.total_score, 0) AS current_total_score
                FROM users
                LEFT JOIN user_ratings USING (telegram_id)
                WHERE users.telegram_id <> %(telegram_id)s
                  AND users.age IS NOT NULL
                  AND users.gender IS NOT NULL
                  AND users.city IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM user_interactions
                    WHERE requester_telegram_id = %(telegram_id)s
                      AND responder_telegram_id = users.telegram_id
                  )
                ORDER BY current_total_score DESC, users.updated_at DESC
                """,
                {"telegram_id": telegram_id},
            ).fetchall()

        candidates = [
            self._row_to_user(row)
            for row in rows
            if _matches_preferences(requester, self._row_to_user(row))
        ]
        return candidates[:limit]

    def is_feed_candidate(self, requester_telegram_id: int, candidate_telegram_id: int) -> bool:
        requester = self.get_user(requester_telegram_id)
        candidate = self.get_user(candidate_telegram_id)
        if requester is None or candidate is None:
            return False

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM user_interactions
                WHERE requester_telegram_id = %(requester)s
                  AND responder_telegram_id = %(candidate)s
                """,
                {"requester": requester_telegram_id, "candidate": candidate_telegram_id},
            ).fetchone()

        return row is None and requester_telegram_id != candidate_telegram_id and _matches_preferences(
            requester, candidate
        )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("TRUNCATE user_interactions, user_photos, user_ratings, users RESTART IDENTITY CASCADE")

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _unique_violation_error():
        from psycopg.errors import UniqueViolation

        return UniqueViolation

    def _interaction_stats(self, telegram_id: int) -> InteractionStats:
        with self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS received_total,
                    COUNT(*) FILTER (WHERE is_like) AS received_likes,
                    COUNT(*) FILTER (WHERE NOT is_like) AS received_skips
                FROM user_interactions
                WHERE responder_telegram_id = %(telegram_id)s
                """,
                {"telegram_id": telegram_id},
            ).fetchone()
            mutual = conn.execute(
                """
                SELECT COUNT(*) AS mutual_likes
                FROM user_interactions incoming
                WHERE incoming.responder_telegram_id = %(telegram_id)s
                  AND incoming.is_like = TRUE
                  AND EXISTS (
                    SELECT 1
                    FROM user_interactions outgoing
                    WHERE outgoing.requester_telegram_id = %(telegram_id)s
                      AND outgoing.responder_telegram_id = incoming.requester_telegram_id
                      AND outgoing.is_like = TRUE
                  )
                """,
                {"telegram_id": telegram_id},
            ).fetchone()
            referrals = conn.execute(
                """
                SELECT COUNT(*) AS referrals_count
                FROM users
                WHERE referral_telegram_id = %(telegram_id)s
                """,
                {"telegram_id": telegram_id},
            ).fetchone()

        return InteractionStats(
            received_likes=int(totals["received_likes"] or 0),
            received_skips=int(totals["received_skips"] or 0),
            mutual_likes=int(mutual["mutual_likes"] or 0),
            referrals_count=int(referrals["referrals_count"] or 0),
        )

    def _has_like(self, *, requester_telegram_id: int, responder_telegram_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM user_interactions
                WHERE requester_telegram_id = %(requester)s
                  AND responder_telegram_id = %(responder)s
                  AND is_like = TRUE
                """,
                {"requester": requester_telegram_id, "responder": responder_telegram_id},
            ).fetchone()
        return row is not None

    @staticmethod
    def _row_to_user(row: dict[str, Any]) -> UserRecord:
        return UserRecord(
            telegram_id=int(row["telegram_id"]),
            username=row.get("username"),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            age=row.get("age"),
            gender=row.get("gender"),
            interests=row.get("interests"),
            city=row.get("city"),
            profile_completion_pct=int(row.get("profile_completion_pct") or 0),
            photos_count=int(row.get("photos_count") or 0),
            age_pref_min=row.get("age_pref_min"),
            age_pref_max=row.get("age_pref_max"),
            gender_pref=row.get("gender_pref"),
            city_pref=row.get("city_pref"),
            interests_pref=row.get("interests_pref"),
            last_activity=row.get("last_activity"),
            referral_telegram_id=row.get("referral_telegram_id"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_rating(row: dict[str, Any]) -> RatingRecord:
        return RatingRecord(
            telegram_id=int(row["telegram_id"]),
            primary_score=float(row["primary_score"]),
            behavioral_score=float(row["behavioral_score"]),
            referral_score=float(row["referral_score"]),
            total_score=float(row["total_score"]),
            calculated_at=row["calculated_at"],
        )

    @staticmethod
    def _row_to_interaction(row: dict[str, Any]) -> InteractionRecord:
        return InteractionRecord(
            id=str(row["id"]),
            requester_telegram_id=int(row["requester_telegram_id"]),
            responder_telegram_id=int(row["responder_telegram_id"]),
            is_like=bool(row["is_like"]),
            created_at=row["created_at"],
        )


InMemoryUserRepository = InMemoryDatingRepository

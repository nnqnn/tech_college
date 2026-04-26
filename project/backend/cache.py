from __future__ import annotations

from threading import Lock
from typing import Protocol


class CandidateCache(Protocol):
    def pop_candidate(self, telegram_id: int) -> int | None:
        raise NotImplementedError

    def push_candidates(self, telegram_id: int, candidate_ids: list[int], ttl_seconds: int) -> None:
        raise NotImplementedError

    def clear(self, telegram_id: int | None = None) -> None:
        raise NotImplementedError


class InMemoryCandidateCache:
    def __init__(self) -> None:
        self._items: dict[int, list[int]] = {}
        self._lock = Lock()

    def pop_candidate(self, telegram_id: int) -> int | None:
        with self._lock:
            values = self._items.get(telegram_id)
            if not values:
                return None
            candidate_id = values.pop(0)
            if not values:
                self._items.pop(telegram_id, None)
            return candidate_id

    def push_candidates(self, telegram_id: int, candidate_ids: list[int], ttl_seconds: int) -> None:
        del ttl_seconds
        with self._lock:
            if candidate_ids:
                self._items[telegram_id] = list(candidate_ids)
            else:
                self._items.pop(telegram_id, None)

    def clear(self, telegram_id: int | None = None) -> None:
        with self._lock:
            if telegram_id is None:
                self._items.clear()
            else:
                self._items.pop(telegram_id, None)

    def snapshot(self, telegram_id: int) -> list[int]:
        with self._lock:
            return list(self._items.get(telegram_id, []))


class RedisCandidateCache:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            from redis import Redis

            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def pop_candidate(self, telegram_id: int) -> int | None:
        raw_value = self.redis.lpop(self._key(telegram_id))
        if raw_value is None:
            return None
        return int(raw_value)

    def push_candidates(self, telegram_id: int, candidate_ids: list[int], ttl_seconds: int) -> None:
        key = self._key(telegram_id)
        pipe = self.redis.pipeline()
        pipe.delete(key)
        if candidate_ids:
            pipe.rpush(key, *[str(candidate_id) for candidate_id in candidate_ids])
            pipe.expire(key, ttl_seconds)
        pipe.execute()

    def clear(self, telegram_id: int | None = None) -> None:
        if telegram_id is not None:
            self.redis.delete(self._key(telegram_id))
            return

        for key in self.redis.scan_iter("candidates:*"):
            self.redis.delete(key)

    @staticmethod
    def _key(telegram_id: int) -> str:
        return f"candidates:{telegram_id}"

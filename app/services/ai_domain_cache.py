"""Redis-backed cache with an in-memory fallback for AI Domains."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as redis

from app.core.config import settings


class AIDomainCache:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._memory: dict[str, tuple[float, Any]] = {}

    async def _client(self) -> redis.Redis | None:
        if not settings.REDIS_URL.strip():
            return None
        if self._redis is None:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def get_json(self, key: str) -> Any | None:
        client = await self._client()
        if client is not None:
            raw = await client.get(key)
            return json.loads(raw) if raw else None

        entry = self._memory.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= time.time():
            self._memory.pop(key, None)
            return None
        return value

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        client = await self._client()
        if client is not None:
            await client.setex(key, ttl_seconds, json.dumps(value, default=str))
            return
        self._memory[key] = (time.time() + ttl_seconds, value)

    async def increment_daily(self, key: str) -> int:
        return await self.increment_window(key, self._seconds_until_next_utc_day())

    async def increment_window(self, key: str, window_seconds: int) -> int:
        """Increment a counter with an explicit TTL window (Redis or memory).

        Used by the referral rate limiter for sliding per-identity / per-token
        windows. Returns the new count (1 on first increment in the window).
        """
        ttl = max(60, int(window_seconds))
        client = await self._client()
        if client is not None:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl)
            value, _ = await pipe.execute()
            return int(value)

        now = time.time()
        entry = self._memory.get(key)
        if not entry or entry[0] <= now:
            self._memory[key] = (now + ttl, 1)
            return 1
        expires_at, count = entry
        next_count = int(count) + 1
        self._memory[key] = (expires_at, next_count)
        return next_count

    @staticmethod
    def _seconds_until_next_utc_day() -> int:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).date()
        next_day = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc)
        return max(60, int((next_day - now).total_seconds()))


ai_domain_cache = AIDomainCache()

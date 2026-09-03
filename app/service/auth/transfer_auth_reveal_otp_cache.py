"""OTP cache for auth-code reveal (mirrors SignupOtpCache)."""

from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as redis

from app.core.config import settings


class TransferAuthRevealOtpCache:
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

    async def delete(self, key: str) -> None:
        client = await self._client()
        if client is not None:
            await client.delete(key)
            return
        self._memory.pop(key, None)


transfer_auth_reveal_otp_cache = TransferAuthRevealOtpCache()

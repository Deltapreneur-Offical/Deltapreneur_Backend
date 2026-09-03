"""Backend-enforced daily limits for AI Domains searches."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Request

from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.services.cache_service import ai_domain_cache


class AIDomainRateLimiter:
    async def check(self, request: Request, user: AppUser | None) -> int | None:
        if self._is_unlimited(user):
            return None

        limit = (
            settings.AI_DOMAIN_RATE_LIMIT_AUTH_DAILY
            if user
            else settings.AI_DOMAIN_RATE_LIMIT_GUEST_DAILY
        )
        identity = self._identity(request, user)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"ai_domains:rate:{day}:{identity}"
        used = await ai_domain_cache.increment_daily(key)
        remaining = max(0, limit - used)
        if used > limit:
            label = "authenticated" if user else "guest"
            raise AppException(
                f"AI Domains daily limit reached for {label} searches.",
                status_code=429,
            )
        return remaining

    @staticmethod
    def _is_unlimited(user: AppUser | None) -> bool:
        role = str(getattr(getattr(user, "role", None), "value", "") or "").upper()
        return role in {"PREMIUM", "ADMIN_UNLIMITED"}

    @staticmethod
    def _identity(request: Request, user: AppUser | None) -> str:
        if user:
            return f"user:{user.id}"
        guest = (
            request.headers.get("x-guest-session")
            or request.cookies.get("guest_session")
            or get_client_ip(request)
        )
        digest = hashlib.sha256(str(guest).encode("utf-8")).hexdigest()[:32]
        return f"guest:{digest}"


ai_domain_rate_limiter = AIDomainRateLimiter()

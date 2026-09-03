"""Anti-abuse rate limits for referral tracking.

Reuses the existing Redis-backed ``AIDomainCache`` counter (in-memory fallback
when Redis is unset) — no new infrastructure. Limits are additive defaults in
``app.core.config.Settings`` and can be tuned per environment.
"""

from __future__ import annotations

import hashlib

from app.core.config import settings
from app.services.cache_service import ai_domain_cache


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class ReferralRateLimiter:
    """Per-identity / per-token / per-referrer windows for referral rewards."""

    async def check_track(self, *, identity: str, token: str | None) -> bool:
        """Rate-limit track requests by receiver identity and share token."""
        identity_used = await ai_domain_cache.increment_window(
            f"referral:track:identity:{_digest(identity)}",
            settings.REFERRAL_TRACK_LIMIT_WINDOW_SECONDS,
        )
        if identity_used > settings.REFERRAL_TRACK_LIMIT_PER_IDENTITY:
            return False
        if token:
            token_used = await ai_domain_cache.increment_window(
                f"referral:track:token:{_digest(token)}",
                settings.REFERRAL_TRACK_LIMIT_WINDOW_SECONDS,
            )
            if token_used > settings.REFERRAL_TRACK_LIMIT_PER_TOKEN:
                return False
        return True

    async def check_reward(self, referrer_id) -> bool:
        """Rate-limit daily rewarded referrals per referrer."""
        used = await ai_domain_cache.increment_window(
            f"referral:reward:referrer:{referrer_id}",
            86400,
        )
        return used <= settings.REFERRAL_REWARD_LIMIT_PER_REFERRER_DAILY


referral_rate_limiter = ReferralRateLimiter()

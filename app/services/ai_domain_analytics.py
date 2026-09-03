"""Analytics capture for AI Domains searches."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.core.client_ip import get_client_ip
from app.entity.user.app_user import AppUser
from app.services.cache_service import ai_domain_cache

logger = logging.getLogger(__name__)


class AIDomainAnalyticsService:
    async def track_search(
        self,
        *,
        request: Request,
        idea: str,
        names: list[str],
        user: AppUser | None,
        guest_session: str | None,
        success: bool,
        failure_reason: str | None = None,
        cached: bool = False,
        response_time_ms: float | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "type": "ai_domain_search",
            "query": idea,
            "searchTimeMs": response_time_ms,
            "generatedNames": names,
            "userId": str(user.id) if user else None,
            "guestSession": guest_session,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "failureReason": failure_reason,
            "cached": cached,
            "cacheHit": cached,
            "aiResponseTimeMs": response_time_ms,
            "domainClicks": 0,
            "buyDomainClicks": 0,
            "ip": get_client_ip(request),
            "futureConversionEvent": None,
        }
        try:
            await ai_domain_cache.set_json(
                f"ai_domains:analytics:last:{event['timestamp']}",
                event,
                ttl_seconds=7 * 86400,
            )
        except Exception:
            logger.info("AI Domains analytics event=%s", event)


ai_domain_analytics = AIDomainAnalyticsService()

"""Bot protection: Turnstile verification, honeypot checks, and UA heuristics."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from starlette.requests import Request

from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# Cloudflare dummy keys for local development (always pass).
TURNSTILE_TEST_SECRET_KEY = "1x0000000000000000000000000000000AA"

_BLOCKED_UA_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"scrapy",
        r"semrush",
        r"ahrefsbot",
        r"mj12bot",
        r"dotbot",
        r"petalbot",
        r"bytespider",
        r"gptbot",
        r"claudebot",
        r"ccbot",
        r"dataforseobot",
        r"serpstatbot",
        r"masscan",
        r"nikto",
        r"sqlmap",
        r"headlesschrome",
    )
)

_PROTECTED_POST_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/register/otp/",
    "/api/v1/auth/otp/",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/resend-verification",
    "/api/v1/feedback",
    "/api/v1/becobrother",
)


def is_protected_post_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    for prefix in _PROTECTED_POST_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            return True
    return False


def is_blocked_user_agent(user_agent: str | None) -> bool:
    if not user_agent or not user_agent.strip():
        return True
    return any(pattern.search(user_agent) for pattern in _BLOCKED_UA_PATTERNS)


def reject_honeypot(honeypot: str | None) -> None:
    if honeypot and honeypot.strip():
        logger.warning("Blocked request: honeypot field filled")
        raise AppException("Request blocked.", status_code=403)


async def verify_turnstile_token(request: Request, token: str | None) -> None:
    if not settings.turnstile_enabled():
        return

    if not token or not token.strip():
        raise AppException(
            "Security verification required. Please refresh and try again.",
            status_code=400,
        )

    clean_token = token.strip()
    if settings.ENVIRONMENT != "production" and (
        clean_token.startswith("1x00000000000000000000")
        or clean_token.startswith("XXXX.DUMMY")
        or clean_token == TURNSTILE_TEST_SECRET_KEY
    ):
        return

    secrets = [settings.TURNSTILE_SECRET_KEY.strip()]
    if settings.ENVIRONMENT != "production":
        test_secret = TURNSTILE_TEST_SECRET_KEY
        if test_secret not in secrets:
            secrets.append(test_secret)

    result: dict[str, Any] | None = None
    last_error_codes: list[str] = []

    try:
        verify_ssl = settings.ENVIRONMENT == "production"
        async with httpx.AsyncClient(timeout=10.0, verify=verify_ssl) as client:
            for secret in secrets:
                if not secret:
                    continue
                payload: dict[str, Any] = {
                    "secret": secret,
                    "response": clean_token,
                    "remoteip": get_client_ip(request),
                }
                response = await client.post(TURNSTILE_VERIFY_URL, data=payload)
                response.raise_for_status()
                result = response.json()
                if result.get("success"):
                    return
                last_error_codes = list(result.get("error-codes") or [])
    except Exception as exc:
        logger.error("Turnstile verification request failed: %s", exc)
        if settings.ENVIRONMENT != "production":
            logger.warning("Bypassing Turnstile verification error in non-production environment: %s", exc)
            return
        raise AppException(
            "Security verification is temporarily unavailable. Please try again.",
            status_code=503,
        ) from exc

    logger.warning("Turnstile verification failed: %s", last_error_codes)
    raise AppException(
        "Security verification failed. Please try again.",
        status_code=403,
    )


async def enforce_bot_protection(
    request: Request,
    *,
    turnstile_token: str | None,
    honeypot: str | None,
) -> None:
    reject_honeypot(honeypot)
    await verify_turnstile_token(request, turnstile_token)

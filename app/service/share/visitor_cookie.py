"""Server-issued, signed anonymous visitor identity (``cb_visitor`` cookie).

The cookie value is ``<uuid4>.<hmac-sha256(uuid4, JWT_SECRET_KEY)>``. It is
HttpOnly / SameSite=Lax / Secure (production) so clients cannot forge or read
it, and it gives anonymous receivers a stable, privacy-conscious identity for
referral dedupe without fingerprinting. When the cookie is missing or
tampered-with, callers fall back to the client IP (today's behavior).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi import Request

from app.core.config import settings

COOKIE_NAME = "cb_visitor"
COOKIE_MAX_AGE = 180 * 24 * 3600  # 180 days


def _sign(visitor_uuid: str) -> str:
    return hmac.new(
        settings.JWT_SECRET_KEY.encode("utf-8"),
        visitor_uuid.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_visitor_value() -> str:
    """Return a fresh signed visitor cookie value."""
    visitor_uuid = str(uuid.uuid4())
    return f"{visitor_uuid}.{_sign(visitor_uuid)}"


def parse_visitor_value(value: str | None) -> str | None:
    """Verify a cookie value and return the embedded visitor UUID, or None."""
    if not value or not isinstance(value, str):
        return None
    try:
        visitor_uuid, signature = value.rsplit(".", 1)
        uuid.UUID(visitor_uuid)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(_sign(visitor_uuid), signature):
        return None
    return visitor_uuid


def read_visitor_key(request: Request) -> str | None:
    """Resolve the verified visitor UUID from the request's cookie, or None."""
    return parse_visitor_value(request.cookies.get(COOKIE_NAME))


def set_visitor_cookie(response, value: str | None = None) -> str:
    """Set the cb_visitor cookie on a response; returns the stored visitor UUID."""
    if not value:
        value = create_visitor_value()
    response.set_cookie(
        key=COOKIE_NAME,
        value=value,
        max_age=COOKIE_MAX_AGE,
        path="/",
        secure=settings.ENVIRONMENT == "production",
        httponly=True,
        samesite="lax",
    )
    parsed = parse_visitor_value(value)
    return parsed or ""

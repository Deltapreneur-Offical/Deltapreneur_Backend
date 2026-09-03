import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from app.core.config import settings

_STATE_TTL_SECONDS = 600
_COOKIE_NAME = "oauth_state"


def _sign(payload_b64: str) -> str:
    return hmac.new(
        settings.JWT_SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()


def create_oauth_state(provider: str = "google", **extra: Any) -> str:
    payload: dict[str, Any] = {
        "nonce": secrets.token_urlsafe(16),
        "provider": provider,
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    payload_b64 = urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode(),
    ).decode()
    return f"{payload_b64}.{_sign(payload_b64)}"


def parse_oauth_state(state: str, *, provider: str = "google") -> dict[str, Any] | None:
    """Return verified payload or None if invalid/expired/wrong provider."""
    if not state or "." not in state:
        return None
    payload_b64, signature = state.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload_b64), signature):
        return None
    try:
        payload = json.loads(urlsafe_b64decode(payload_b64.encode()))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("provider") != provider:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def verify_oauth_state(state: str, *, provider: str = "google") -> bool:
    return parse_oauth_state(state, provider=provider) is not None


def oauth_state_cookie_name() -> str:
    return _COOKIE_NAME

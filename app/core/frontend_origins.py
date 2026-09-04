"""Allow-listed SPA origins for OAuth return URLs and Host-based cookie domains.

This isolated Deltapreneur API only honors deltapreneur.com. CoBrother and
HubRegistrar hosts are not CORS/return origins here, so those SPAs cannot call
this API or steal OAuth success redirects.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.requests import Request

from app.core.config import settings

_SPA_ORIGIN_RE = re.compile(
    r"^https://([a-z0-9-]+\.)*deltapreneur\.com$",
    re.IGNORECASE,
)
_DEV_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
}


def request_hostname(request: Request | None) -> str:
    if request is None:
        return ""
    host = (request.headers.get("host") or "").split(",")[0].strip()
    if not host:
        try:
            host = request.url.hostname or ""
        except Exception:
            host = ""
    return host.split(":")[0].strip().lower()


def brand_for_hostname(hostname: str | None) -> str | None:
    host = (hostname or "").split(":")[0].strip().lower()
    if not host:
        return None
    if host == "deltapreneur.com" or host.endswith(".deltapreneur.com"):
        return "deltapreneur"
    return None


def normalize_origin(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    parts = urlsplit(str(value).strip())
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.netloc or "@" in parts.netloc:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


def _explicit_allowed_origins() -> set[str]:
    allowed = {
        "https://deltapreneur.com",
        "https://www.deltapreneur.com",
        *_DEV_ORIGINS,
    }
    frontend = (settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    if frontend:
        allowed.add(frontend)
    for item in (settings.CORS_ALLOW_ORIGINS or "").split(","):
        cleaned = item.strip().rstrip("/")
        if cleaned:
            allowed.add(cleaned)
    return allowed


def allowed_frontend_return_origin(return_origin: str | None) -> str | None:
    """Return a safe SPA origin or None. Rejects open redirects and API hosts."""
    origin = normalize_origin(return_origin)
    if not origin:
        return None
    host = (urlsplit(origin).hostname or "").lower()
    if host.startswith("backend.") or host.startswith("api."):
        return None
    if origin in _explicit_allowed_origins():
        return origin
    if _SPA_ORIGIN_RE.match(origin):
        return origin
    return None


def gated_frontend_origin(
    *,
    return_origin: str | None,
    request: Request | None,
) -> str | None:
    """Honor Deltapreneur return_origin only when the API Host is Deltapreneur.

    Missing, invalid, or brand-mismatched origins return None so callers keep
    FRONTEND_BASE_URL / GOOGLE_OAUTH_SUCCESS_REDIRECT.
    """
    allowed = allowed_frontend_return_origin(return_origin)
    if not allowed:
        return None
    origin_brand = brand_for_hostname(urlsplit(allowed).hostname)
    host_brand = brand_for_hostname(request_hostname(request))
    if origin_brand is None or host_brand is None:
        return None
    if origin_brand != host_brand:
        return None
    return allowed


def cookie_domain_for_request(request: Request | None) -> str | None:
    host = request_hostname(request)
    brand = brand_for_hostname(host)
    if brand == "deltapreneur":
        return ".deltapreneur.com"
    configured = (settings.AUTH_COOKIE_DOMAIN or "").strip()
    return configured or None


def google_oauth_redirect_uri_for_request(request: Request | None = None) -> str:
    """Use GOOGLE_OAUTH_REDIRECT_URI. Do not invent a second Google client.

    GOOGLE_OAUTH_REDIRECT_URI_HUBREGISTRAR is an unused leftover on this API.
    """
    cobrother = (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    if cobrother:
        return cobrother
    base = (settings.BACKEND_BASE_URL or "").rstrip("/")
    return f"{base}/api/v1/auth/oauth/google/callback"


def linkedin_oauth_redirect_uri_for_request(request: Request | None = None) -> str:
    """Use LINKEDIN_REDIRECT_URI / BACKEND_BASE_URL. Hub leftover is unused."""
    cobrother = (settings.LINKEDIN_REDIRECT_URI or "").strip()
    if cobrother:
        return cobrother
    base = (settings.BACKEND_BASE_URL or "").rstrip("/")
    return f"{base}/api/v1/auth/oauth/linkedin/callback"

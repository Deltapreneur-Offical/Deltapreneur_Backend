"""Allow-listed SPA origins for OAuth return URLs and Host-based cookie domains.

CoBrother production URLs stay the default. HubRegistrar is honored only when the
API Host matches that brand, so an unset Hub Google callback cannot hijack login.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.requests import Request

from app.core.config import settings

_SPA_ORIGIN_RE = re.compile(
    r"^https://([a-z0-9-]+\.)*(cobrother|hubregistrar)\.com$",
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
    if host == "hubregistrar.com" or host.endswith(".hubregistrar.com"):
        return "hubregistrar"
    if host == "cobrother.com" or host.endswith(".cobrother.com"):
        return "cobrother"
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
        "https://cobrother.com",
        "https://www.cobrother.com",
        "https://hubregistrar.com",
        "https://www.hubregistrar.com",
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
    if host.startswith("backend."):
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
    """Honor HubRegistrar return_origin only when the API Host is HubRegistrar.

    Missing, invalid, or brand-mismatched origins return None so callers keep
    FRONTEND_BASE_URL / GOOGLE_OAUTH_SUCCESS_REDIRECT (CoBrother today).
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
    if brand == "hubregistrar":
        return ".hubregistrar.com"
    if brand == "cobrother":
        return ".cobrother.com"
    configured = (settings.AUTH_COOKIE_DOMAIN or "").strip()
    return configured or None


def google_oauth_redirect_uri_for_request(request: Request | None = None) -> str:
    """CoBrother Google callback stays the default. Hub URI is additive only."""
    host = request_hostname(request)
    if brand_for_hostname(host) == "hubregistrar":
        hub = (settings.GOOGLE_OAUTH_REDIRECT_URI_HUBREGISTRAR or "").strip()
        if hub:
            return hub
    cobrother = (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    if cobrother:
        return cobrother
    base = (settings.BACKEND_BASE_URL or "").rstrip("/")
    return f"{base}/api/v1/auth/oauth/google/callback"


_LINKEDIN_COMMUNITY_CALLBACK_PATH = "/api/v1/community/linkedin/callback"


def linkedin_oauth_redirect_uri_for_request(request: Request | None = None) -> str:
    """CoBrother LinkedIn callback stays the default. Hub URI is additive only."""
    host = request_hostname(request)
    if brand_for_hostname(host) == "hubregistrar":
        hub = (settings.LINKEDIN_REDIRECT_URI_HUBREGISTRAR or "").strip()
        if hub:
            return hub
        hostname = (host or "").split(":")[0].strip().lower()
        if hostname:
            return f"https://{hostname}{_LINKEDIN_COMMUNITY_CALLBACK_PATH}"
    cobrother = (settings.LINKEDIN_REDIRECT_URI or "").strip()
    if cobrother:
        return cobrother
    base = (settings.BACKEND_BASE_URL or "").rstrip("/")
    return f"{base}/api/v1/auth/oauth/linkedin/callback"

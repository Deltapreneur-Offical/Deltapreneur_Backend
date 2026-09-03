"""OpenProvider REST client (domain registration)."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx

from app.core.config import settings
from fastapi import status as http_status

logger = logging.getLogger(__name__)

# Force IPv4 resolution for OpenProvider hosts. On dual-stack hosts the OS may
# egress over IPv6, but the OpenProvider API IP whitelist typically lists only
# an IPv4 address — that mismatch makes every data call fail with code=10005
# "Access denied" (login still works). Scoped to openprovider hosts so other
# outbound calls (Razorpay, etc.) are unaffected.
import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if settings.OPENPROVIDER_FORCE_IPV4 and "openprovider" in str(host):
        family = _socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


_socket.getaddrinfo = _ipv4_getaddrinfo

_token: Optional[str] = None
_token_expiry: float = 0.0
_auth_lock: Optional[asyncio.Lock] = None
_auth_cooldown_until: float = 0.0
_login_attempt_times: deque[float] = deque()
_auth_cooldown_logged_open: bool = False

# Auth hardening defaults (process-local; must not flood OpenProvider).
_AUTH_COOLDOWN_SECONDS = 600.0
_LOGIN_RATE_LIMIT = 10
_LOGIN_RATE_WINDOW_SECONDS = 60.0
_TOKEN_REFRESH_MARGIN_SECONDS = 60.0
_TOKEN_FALLBACK_TTL_SECONDS = 19 * 60
# Structured OpenProvider auth/token failure codes (not Access denied / IP).
_AUTH_FAILURE_CODES = frozenset({196})
_AUTH_DESC_MARKERS = frozenset(
    {
        "invalid token",
        "authentication failed",
        "authorization failed",
        "authentication/authorization failed",
        "unauthorized",
        "token expired",
    }
)

# Cache the active-TLD catalog. It changes very rarely but is fetched on every
# domain search (for the remaining/"Load more" scan), so caching it removes a
# slow registrar round-trip from the hot path. ``_tld_catalog_src_id`` records
# the identity of the ``list_active_tlds`` function used to populate the cache,
# so monkeypatched test doubles are never served stale cached data.
_tld_catalog_cache: Optional[list[str]] = None
_tld_catalog_expiry: float = 0.0
_tld_catalog_src_id: int = 0
_TLD_CATALOG_TTL_SECONDS = 6 * 60 * 60


def _base_url() -> str:
    return settings.resolved_openprovider_api_base_url()


def http_status_for_openprovider_error(error_message: str) -> int:
    """Map an OpenProvider error to an appropriate HTTP status code."""
    if not error_message:
        return http_status.HTTP_502_BAD_GATEWAY

    lower = str(error_message).lower()

    if "login failed" in lower or "login rejected" in lower:
        return http_status.HTTP_502_BAD_GATEWAY

    if "access denied" in lower or "code=10005" in lower:
        return http_status.HTTP_403_FORBIDDEN

    if "not found" in lower:
        return http_status.HTTP_404_NOT_FOUND

    if "rate limit" in lower or "too many requests" in lower:
        return http_status.HTTP_429_TOO_MANY_REQUESTS

    return http_status.HTTP_502_BAD_GATEWAY


def is_sandbox() -> bool:
    return settings.openprovider_use_sandbox()


def control_panel_url() -> str:
    if is_sandbox():
        return "https://cp.sandbox.openprovider.nl"
    return "https://cp.openprovider.eu"


def _username() -> str:
    return settings.OPENPROVIDER_USERNAME.strip()


def _password() -> str:
    return settings.OPENPROVIDER_PASSWORD.strip()


def _client_ip() -> str:
    ip = (settings.OPENPROVIDER_CLIENT_IP or "").strip()
    # Don't bind the session to loopback/placeholder IPs. An empty value lets
    # OpenProvider accept requests from the server's actual egress IP (required
    # when running behind a dynamic/residential IP). Binding to a stale IP makes
    # every post-login call fail with code=10005 "Access denied".
    if ip in ("", "127.0.0.1", "0.0.0.0", "::1"):
        return ""
    return ip


def _default_nameservers() -> list[str]:
    raw = settings.OPENPROVIDER_DEFAULT_NAMESERVERS
    return [_normalize_ns_host(ns) for ns in raw.split(",") if ns.strip()]


def default_nameservers() -> list[str]:
    """Public accessor for the platform default nameservers (customer-facing vanity hosts)."""
    hosts = _default_nameservers()
    if not hosts:
        raise RuntimeError(
            "OPENPROVIDER_DEFAULT_NAMESERVERS is empty. "
            "Set vanity hosts e.g. ns1.hubregistrar.com,ns2.hubregistrar.com,ns3.hubregistrar.com"
        )
    return hosts


# Legacy OpenProvider shared-group hosts (pre-vanity). Existing customer domains
# may still use these; keep them as "platform DNS" so zone management works.
_LEGACY_OPENPROVIDER_GROUP_NAMESERVERS = frozenset(
    {
        "ns1.openprovider.nl",
        "ns2.openprovider.be",
        "ns3.openprovider.eu",
    }
)

# Built-in CoBrother vanity hosts (NS group "CoBrother"). Always treated as
# platform DNS even if env temporarily lists a subset.
_COBROTHER_VANITY_NAMESERVERS = frozenset(
    {
        "ns1.cobrother.com",
        "ns2.cobrother.com",
        "ns3.cobrother.com",
    }
)

# Built-in HubRegistrar vanity hosts (NS group "HubRegistrar"). Always treated
# as platform DNS even if env still lists CoBrother (or a subset).
_HUBREGISTRAR_VANITY_NAMESERVERS = frozenset(
    {
        "ns1.hubregistrar.com",
        "ns2.hubregistrar.com",
        "ns3.hubregistrar.com",
    }
)

# Backward-compatible alias used by older imports/tests.
_OPENPROVIDER_GROUP_NAMESERVERS = _LEGACY_OPENPROVIDER_GROUP_NAMESERVERS


def _normalize_ns_host(host: object) -> str:
    return str(host or "").strip().rstrip(".").lower()


def parse_nameservers_from_details(details: dict[str, Any]) -> list[str]:
    """Extract nameserver hosts from a GET /v1beta/domains/{id} response.

    OpenProvider returns ``"name_servers": [{"name": "ns1.openprovider.nl", ...}]``.
    Returns normalized (lowercase, no trailing dot) deduplicated hosts, or an
    empty list when the shape is missing/unknown so callers never overwrite
    stored values with garbage.
    """
    raw = details.get("name_servers") or details.get("nameservers") or []
    if not isinstance(raw, list):
        return []
    hosts: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = _normalize_ns_host(item.get("name"))
        else:
            name = _normalize_ns_host(item)
        if name and name not in hosts:
            hosts.append(name)
    return hosts


def is_platform_nameserver_set(hosts: list[str]) -> bool:
    """True when the given nameserver hosts mean "DNS is managed by us".

    - Empty list: assume platform defaults (legacy orders with nothing stored).
    - Otherwise every host must be a known platform nameserver:
      configured OPENPROVIDER_DEFAULT_NAMESERVERS, HubRegistrar vanity hosts,
      CoBrother vanity hosts, or legacy OpenProvider group hosts
      (existing customer domains).
    """
    normalized = {_normalize_ns_host(h) for h in hosts}
    normalized.discard("")
    if not normalized:
        return True
    known = (
        {_normalize_ns_host(ns) for ns in _default_nameservers()}
        | _HUBREGISTRAR_VANITY_NAMESERVERS
        | _COBROTHER_VANITY_NAMESERVERS
        | _LEGACY_OPENPROVIDER_GROUP_NAMESERVERS
    )
    return normalized.issubset(known)


def is_configured() -> bool:
    return settings.openprovider_configured()


def _format_http_error(operation: str, status_code: int, body_text: str) -> str:
    """Human-readable message for failed registrar HTTP calls."""
    preview = (body_text or "").strip()[:400]
    panel = control_panel_url()
    env_label = "sandbox" if is_sandbox() else "production"
    hint = (
        f"Check registrar API credentials ({env_label}), set "
        "CLIENT_IP to this server's public IP, and in "
        f"{panel} ensure API access is enabled for the contact and API IP whitelist "
        "allows that IP (or is empty for testing)."
    )
    if not preview:
        return (
            f"Registrar {operation} failed (HTTP {status_code}, empty response). {hint} "
            "If HTTP 500 persists, the service may be having an outage — retry later."
        )
    try:
        data = json.loads(body_text)
        if isinstance(data, dict):
            desc = data.get("desc") or data.get("message") or data.get("error")
            code = data.get("code")
            if desc or code is not None:
                return (
                    f"Registrar {operation} failed (HTTP {status_code}, code={code}): {desc}. {hint}"
                )
    except (json.JSONDecodeError, TypeError):
        pass
    return f"Registrar {operation} failed (HTTP {status_code}): {preview}. {hint}"


def _get_auth_lock() -> asyncio.Lock:
    global _auth_lock
    if _auth_lock is None:
        _auth_lock = asyncio.Lock()
    return _auth_lock


def _clear_cached_token(*, reason: str = "") -> None:
    global _token, _token_expiry
    had_token = bool(_token)
    _token = None
    _token_expiry = 0.0
    if had_token or reason:
        logger.warning(
            "[OPENPROVIDER_AUTH] Token invalidated%s",
            f" ({reason})" if reason else "",
        )


def _auth_in_cooldown() -> bool:
    return time.time() < _auth_cooldown_until


def _trip_auth_circuit(reason: str) -> None:
    global _auth_cooldown_until, _auth_cooldown_logged_open
    _auth_cooldown_until = time.time() + _AUTH_COOLDOWN_SECONDS
    _auth_cooldown_logged_open = True
    logger.error(
        "[OPENPROVIDER_AUTH] Circuit breaker activated for %.0fs. Reason: %s",
        _AUTH_COOLDOWN_SECONDS,
        reason,
    )


def _enforce_login_rate_limit() -> None:
    """Refuse login bursts that would approach OpenProvider's auth rate limit."""
    now = time.time()
    while _login_attempt_times and now - _login_attempt_times[0] >= _LOGIN_RATE_WINDOW_SECONDS:
        _login_attempt_times.popleft()
    if len(_login_attempt_times) >= _LOGIN_RATE_LIMIT:
        _trip_auth_circuit(
            f"login rate limit exceeded ({_LOGIN_RATE_LIMIT}/{int(_LOGIN_RATE_WINDOW_SECONDS)}s)"
        )
        raise RuntimeError(
            "OpenProvider authentication rate limit reached locally. "
            "Failing fast to avoid further invalid authentication requests. "
            f"Retry after {_AUTH_COOLDOWN_SECONDS:.0f}s cooldown."
        )
    _login_attempt_times.append(now)


def _parse_response_json(resp: httpx.Response) -> dict[str, Any] | None:
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _response_is_auth_error(resp: httpx.Response) -> bool:
    """Detect OpenProvider authentication failures (status-first, then structured body).

    HTTP status is checked first. Body/JSON is inspected only when status alone
    is insufficient. Free-text matching alone never classifies an auth error.
    code=10005 (Access denied / IP whitelist) is NOT treated as recoverable
    invalid-token (no re-login churn).
    """
    status = int(resp.status_code or 0)
    if status == 401:
        return True

    # 403 alone is insufficient (may be permission/IP). Inspect body only below.
    if status < 400:
        return False

    body = _parse_response_json(resp)
    if body is None:
        return False

    code = body.get("code")
    try:
        code_int = int(code) if code is not None else None
    except (TypeError, ValueError):
        code_int = None

    # Permanent IP / access denial — not an invalid-token refresh case.
    if code_int == 10005:
        return False

    if code_int is not None and code_int in _AUTH_FAILURE_CODES:
        return True

    # Status alone was insufficient; allow known auth phrases only with a
    # structured body and HTTP error status (not free-text-only classification).
    if status in (400, 401, 403, 500) and code_int is not None:
        desc = str(body.get("desc") or body.get("message") or body.get("error") or "").strip().lower()
        if desc in _AUTH_DESC_MARKERS:
            return True
        # Common OP wording variants that include the marker as the full desc.
        for marker in _AUTH_DESC_MARKERS:
            if desc == marker or desc.startswith(marker + ".") or desc.startswith(marker + " "):
                return True

    return False


def _parse_token_expiry(body: dict[str, Any]) -> float:
    """Absolute epoch expiry for the cached token (refresh slightly before OP expiry)."""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    now = time.time()
    ttl: float | None = None

    expires_in = data.get("expires_in")
    if expires_in is None:
        expires_in = body.get("expires_in")
    if expires_in is not None:
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError):
            ttl = None

    if ttl is None:
        for key in ("expiry", "expires_at", "expiration", "expire"):
            raw = data.get(key) if data else None
            if raw is None:
                raw = body.get(key)
            if raw is None:
                continue
            try:
                absolute = float(raw)
                # Heuristic: values that look like epoch seconds.
                if absolute > now:
                    return max(now + 60.0, absolute - _TOKEN_REFRESH_MARGIN_SECONDS)
                ttl = absolute
                break
            except (TypeError, ValueError):
                continue

    if ttl is None or ttl <= 0:
        ttl = float(_TOKEN_FALLBACK_TTL_SECONDS)

    effective = max(60.0, ttl - _TOKEN_REFRESH_MARGIN_SECONDS)
    return now + effective


async def _get_token() -> str:
    """Return a valid Bearer token; single-flight login with circuit breaker."""
    global _token, _token_expiry, _auth_cooldown_logged_open

    if _auth_in_cooldown():
        remaining = max(0.0, _auth_cooldown_until - time.time())
        raise RuntimeError(
            "OpenProvider authentication circuit breaker is open. "
            f"Failing fast ({remaining:.0f}s remaining). "
            "Fix credentials/API access before retrying."
        )

    now = time.time()
    if _token and now < _token_expiry:
        return _token

    async with _get_auth_lock():
        if _auth_in_cooldown():
            remaining = max(0.0, _auth_cooldown_until - time.time())
            raise RuntimeError(
                "OpenProvider authentication circuit breaker is open. "
                f"Failing fast ({remaining:.0f}s remaining). "
                "Fix credentials/API access before retrying."
            )

        now = time.time()
        if _token and now < _token_expiry:
            return _token

        if _auth_cooldown_logged_open and now >= _auth_cooldown_until:
            logger.info("[OPENPROVIDER_AUTH] Circuit breaker cooldown expired; allowing login.")
            _auth_cooldown_logged_open = False

        _enforce_login_rate_limit()

        logger.info("[OPENPROVIDER_AUTH] Requesting auth token from OpenProvider API...")
        login = {
            "username": _username(),
            "password": _password(),
        }
        client_ip = _client_ip()
        if client_ip:
            login["ip"] = client_ip

        # Raw httpx client — must NOT use the authed wrapper (would recurse).
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                resp = await client.post(
                    f"{_base_url()}/v1beta/auth/login",
                    json=login,
                )
        except Exception as exc:
            _clear_cached_token(reason="login transport error")
            _trip_auth_circuit(f"login transport error: {type(exc).__name__}")
            logger.error("[OPENPROVIDER_AUTH] Authentication failure (transport): %s", exc)
            raise RuntimeError(
                f"OpenProvider auth/login transport failed: {exc}"
            ) from exc

        if resp.status_code >= 400:
            preview = (resp.text or "")[:800]
            logger.error(
                "[OPENPROVIDER_AUTH] Authentication failure HTTP %s: %s",
                resp.status_code,
                preview,
            )
            _clear_cached_token(reason=f"login HTTP {resp.status_code}")
            _trip_auth_circuit(f"login HTTP {resp.status_code}")
            raise RuntimeError(_format_http_error("auth/login", resp.status_code, resp.text or ""))

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            logger.error(
                "[OPENPROVIDER_AUTH] Authentication failure: non-JSON response body: %s",
                (resp.text or "")[:500],
            )
            _clear_cached_token(reason="login non-JSON")
            _trip_auth_circuit("login non-JSON response")
            raise RuntimeError(
                "OpenProvider login returned invalid JSON. "
                "Check OPENPROVIDER_API_BASE_URL and network."
            ) from exc

        if body.get("code") != 0:
            desc = body.get("desc") or body.get("message") or "unknown"
            logger.error(
                "[OPENPROVIDER_AUTH] Authentication failure. Code=%s Desc=%s",
                body.get("code"),
                desc,
            )
            _clear_cached_token(reason=f"login rejected code={body.get('code')}")
            _trip_auth_circuit(f"login rejected code={body.get('code')}")
            raise RuntimeError(
                f"OpenProvider login rejected (code={body.get('code')}): {desc}. "
                "Verify reseller username/password and API access on the contact in cp.openprovider.eu."
            )

        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        token = data.get("token")
        if not token:
            _clear_cached_token(reason="login missing token")
            _trip_auth_circuit("login response missing token")
            raise RuntimeError("OpenProvider login response missing token.")

        _token = str(token)
        _token_expiry = _parse_token_expiry(body if isinstance(body, dict) else {})
        logger.info(
            "[OPENPROVIDER_AUTH] Authentication success. Token refresh scheduled before expiry "
            "(ttl_remaining=%.0fs).",
            max(0.0, _token_expiry - time.time()),
        )
        return _token


async def _auth_headers() -> dict[str, str]:
    token = await _get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


class _AuthedHttpClient:
    """Thin httpx wrapper: inject Bearer auth and retry once on auth errors.

    Preserves all httpx timeout/limits/transport/proxy/SSL/request behavior;
    only authentication handling is added. Uses the same verb methods (get/post/…)
    as the underlying client so existing call sites and test doubles keep working.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send_with_auth_retry(
            lambda **kw: self._client.request(method, url, **kw),
            method=method,
            url=url,
            **kwargs,
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send_with_auth_retry(
            lambda **kw: self._client.get(url, **kw),
            method="GET",
            url=url,
            **kwargs,
        )

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send_with_auth_retry(
            lambda **kw: self._client.post(url, **kw),
            method="POST",
            url=url,
            **kwargs,
        )

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send_with_auth_retry(
            lambda **kw: self._client.put(url, **kw),
            method="PUT",
            url=url,
            **kwargs,
        )

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send_with_auth_retry(
            lambda **kw: self._client.delete(url, **kw),
            method="DELETE",
            url=url,
            **kwargs,
        )

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send_with_auth_retry(
            lambda **kw: self._client.patch(url, **kw),
            method="PATCH",
            url=url,
            **kwargs,
        )

    async def _send_with_auth_retry(
        self,
        send,
        *,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        caller_headers = dict(kwargs.pop("headers", None) or {})
        auth = await _auth_headers()
        headers = {**caller_headers, **auth}
        resp = await send(headers=headers, **kwargs)
        if not _response_is_auth_error(resp):
            return resp

        logger.warning(
            "[OPENPROVIDER_AUTH] Auth error on %s %s (HTTP %s); clearing token and refreshing once.",
            method,
            url,
            resp.status_code,
        )
        _clear_cached_token(reason=f"API {method} HTTP {resp.status_code}")
        # Fresh headers go through _get_token + _auth_lock (single-flight refresh).
        auth = await _auth_headers()
        headers = {**caller_headers, **auth}
        resp2 = await send(headers=headers, **kwargs)
        if _response_is_auth_error(resp2):
            _clear_cached_token(reason=f"retry still auth error HTTP {resp2.status_code}")
            _trip_auth_circuit(f"API auth failed after one refresh (HTTP {resp2.status_code})")
            logger.error(
                "[OPENPROVIDER_AUTH] Authentication still failing after one token refresh "
                "(HTTP %s). Circuit breaker engaged.",
                resp2.status_code,
            )
        return resp2


@asynccontextmanager
async def _op_http_client(**client_kwargs: Any):
    """Create an authed httpx client; forwards all AsyncClient kwargs unchanged."""
    client_kwargs.setdefault("verify", False)
    async with httpx.AsyncClient(**client_kwargs) as client:
        yield _AuthedHttpClient(client)


def reset_openprovider_auth_state_for_tests() -> None:
    """Test helper: clear process-local auth cache/breaker (no network/DB)."""
    global _token, _token_expiry, _auth_cooldown_until, _auth_cooldown_logged_open, _auth_lock
    _token = None
    _token_expiry = 0.0
    _auth_cooldown_until = 0.0
    _auth_cooldown_logged_open = False
    _login_attempt_times.clear()
    _auth_lock = asyncio.Lock()


async def get_domain_price(
    name: str,
    extension_no_dot: str,
    *,
    operation: str = "create",
    period: int = 1,
) -> dict[str, Any]:
    """
    Official OpenProvider ``GET /v1beta/domains/prices`` (GetPrice).

    ``operation`` is typically create | renew | transfer | restore.
    For create/renew/transfer with period=N, OP returns the **full period total**
    (not a per-year rate) when period is supported for that operation.
    """
    ext = extension_no_dot.lower().lstrip(".")
    op = (operation or "create").strip().lower()
    years = max(1, int(period or 1))
    logger.info(
        "[OPENPROVIDER_PRICING] Fetching %s price for %s.%s period=%d",
        op,
        name,
        ext,
        years,
    )
    headers = await _auth_headers()
    params = {
        "domain.name": name,
        "domain.extension": ext,
        "operation": op,
        "period": years,
    }
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/domains/prices",
            headers=headers,
            params=params,
        )
        if resp.status_code >= 400:
            logger.error(
                "[OPENPROVIDER_PRICING] Fetch price failed HTTP %s: %s",
                resp.status_code,
                (resp.text or "")[:800],
            )
            raise RuntimeError(
                _format_http_error("domains/prices", resp.status_code, resp.text or "")
            )
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "OpenProvider domains/prices returned invalid JSON."
            ) from exc

    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        logger.error("[OPENPROVIDER_PRICING] Fetch price rejected. Desc: %s", desc)
        raise RuntimeError(f"Registrar domains/prices error: {desc}")

    data = body.get("data")
    if not isinstance(data, dict):
        logger.error("[OPENPROVIDER_PRICING] Fetch price returned empty data.")
        raise RuntimeError("Registrar domains/prices returned empty data")
    logger.info("[OPENPROVIDER_PRICING] %s price fetched successfully. Data: %s", op, data)
    return data


async def get_create_price(
    name: str,
    extension_no_dot: str,
    *,
    period: int = 1,
    classkey: str | None = None,
) -> dict[str, Any]:
    """Billable create price (GetPrice operation=create). ``classkey`` kept for API compat."""
    _ = classkey  # OpenProvider REST GetPrice does not use ResellerClub classkey
    return await get_domain_price(
        name,
        extension_no_dot,
        operation="create",
        period=period,
    )


async def _check_domain_raw(
    name: str,
    extension_no_dot: str,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    """Single OpenProvider domains/check call (optional aftermarket provider)."""
    headers = await _auth_headers()
    payload: dict[str, Any] = {
        "domains": [{"name": name, "extension": extension_no_dot}],
        "with_price": True,
    }
    if provider:
        payload["provider"] = provider
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/domains/check",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error(
                "[OPENPROVIDER_AVAILABILITY] Check failed HTTP %s provider=%s: %s",
                resp.status_code,
                provider or "registry",
                (resp.text or "")[:800],
            )
            raise RuntimeError(
                _format_http_error("domains/check", resp.status_code, resp.text or "")
            )
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Registrar domains/check returned invalid JSON.") from exc

    results = body.get("data", {}).get("results", [])
    if not results:
        logger.error(
            "[OPENPROVIDER_AVAILABILITY] Check response missing results provider=%s",
            provider or "registry",
        )
        raise RuntimeError("Empty OpenProvider check response")
    return results[0]


async def check_domain(
    name: str,
    extension_no_dot: str,
    *,
    include_aftermarket: bool = True,
) -> dict[str, Any]:
    """
    Check registry availability (+ price).

    When ``include_aftermarket`` is True (checkout / cart), falls back to
    Afternic / Sedo if the registry reports taken. Search UX should pass
    ``include_aftermarket=False`` and load marketplace premiums via the
    dedicated search-premium path so Standard results are not blocked.
    """
    logger.info(
        "[OPENPROVIDER_AVAILABILITY] Checking availability for %s.%s aftermarket=%s",
        name,
        extension_no_dot,
        include_aftermarket,
    )
    result = await _check_domain_raw(name, extension_no_dot)
    logger.info(
        "[OPENPROVIDER_AVAILABILITY] RAW registry check %s.%s: %s",
        name,
        extension_no_dot,
        json.dumps(result, default=str)[:2000],
    )

    if is_free(result) or not include_aftermarket:
        return result

    for provider in ("afternic", "sedo"):
        try:
            am = await _check_domain_raw(name, extension_no_dot, provider=provider)
            logger.info(
                "[OPENPROVIDER_AVAILABILITY] RAW aftermarket check %s.%s provider=%s: %s",
                name,
                extension_no_dot,
                provider,
                json.dumps(am, default=str)[:2000],
            )
            if is_free(am) and extract_is_premium(am):
                am = dict(am)
                am["_premium_provider"] = provider
                return am
        except Exception as exc:
            logger.warning(
                "[OPENPROVIDER_AVAILABILITY] Aftermarket check failed %s.%s provider=%s: %s",
                name,
                extension_no_dot,
                provider,
                exc,
            )

    return result


# In-process cache for aftermarket premium search (label → payload).
_AFTERMARKET_PREMIUM_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_AFTERMARKET_PREMIUM_CACHE_TTL_SEC = 300.0


# TLDs commonly used for premium registry listings, supplementing the
# priority list checked by the standard first-page search. The premium
# endpoint scans these PLUS any extra TLDs from the live catalog (capped)
# so the Premium tab always covers more than the Standard tab alone.
_PREMIUM_SUPPLEMENT_TLDS = (
    "shop", "fyi", "luxury", "game", "global", "sale", "forsale", "digital",
    "email", "media", "news", "studio", "design", "solutions", "services",
    "photography", "guru", "ninja", "express", "market", "marketing",
    "software", "tools", "works", "zone", "run", "health", "money", "rent",
    "art", "auto", "car", "cars", "boat", "casino", "bet", "sex", "porn",
    "tattoo", "bar", "pub", "wine", "beer", "coffee", "yoga", "fit",
    "film", "movie", "music", "band", "fan", "hockey", "football", "soccer",
    "golf", "tennis", "ski", "surf", "garden", "green", "organic", "eco",
    "earth", "bio", "vet", "pet", "dog", "horse", "casa", "immo",
)
# Aftermarket providers (Afternic/Sedo) only operate on common gTLDs.
_AFTERMARKET_CHECK_EXTS = ("com", "net", "org", "io", "co")
# Generous cap: OpenProvider batches occasionally take 30s+ when the registry
# is slow / retrying a 504. The frontend aborts its own request at ~35s.
_PREMIUM_HARD_TIMEOUT_SEC = 30
_PREMIUM_SCAN_CONCURRENCY = 4


async def lookup_aftermarket_premium_checks(
    label: str,
) -> list[dict[str, Any]]:
    """
    Premium marketplace search for a label (cached 5 min on success).

    Registry scan across supplement TLDs (those NOT already covered by the
    standard first-page priority search) runs concurrently with a small
    Afternic/Sedo aftermarket check on the top gTLDs. Whole operation is
    hard-capped at ``_PREMIUM_HARD_TIMEOUT_SEC`` seconds so the endpoint
    never hangs; a timed-out scan is NOT cached so the next request retries.
    """
    import time
    import asyncio

    label = (label or "").strip().lower()
    if not label or "." in label:
        label = label.split(".")[0] if label else ""
    if not label:
        return []

    cache_key = f"premium_v3|{label}"
    now = time.monotonic()
    cached = _AFTERMARKET_PREMIUM_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _AFTERMARKET_PREMIUM_CACHE_TTL_SEC:
        return [dict(x) for x in cached[1]]

    async def _registry_scan() -> list[dict[str, Any]]:
        # Supplement TLDs NOT already in the priority first-page set, so we
        # don't duplicate work the Standard search already does.
        priority_first = set(_priority_tlds_deduped()[:_FIRST_PAGE_PRIORITY_COUNT])
        supplement = [t for t in _PREMIUM_SUPPLEMENT_TLDS if t not in priority_first]

        # Extras from the live catalog (cached) not in priority or supplement,
        # capped at 40 to keep the scan bounded.
        extra_catalog: list[str] = []
        try:
            catalog = await _get_active_tlds_cached(limit=600)
            already = priority_first | set(_PREMIUM_SUPPLEMENT_TLDS)
            extra_catalog = [t.lstrip(".") for t in catalog if t.lstrip(".") not in already][:40]
        except Exception as exc:
            logger.warning("[OPENPROVIDER_PREMIUM] catalog fetch skipped: %s", exc)

        tlds_to_check = supplement + extra_catalog
        if not tlds_to_check:
            return []

        logger.info(
            "[OPENPROVIDER_PREMIUM] registry scan for %s: %s supplement + %s catalog TLDs",
            label, len(supplement), len(extra_catalog),
        )
        return await _check_tld_batches(
            label,
            tlds_to_check,
            concurrency=_PREMIUM_SCAN_CONCURRENCY,
            max_retries=2,
        )

    async def _aftermarket_scan() -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(2)

        async def _one(ext: str) -> dict[str, Any] | None:
            async with sem:
                for provider in ("afternic", "sedo"):
                    try:
                        am = await _check_domain_raw(label, ext, provider=provider)
                    except Exception as exc:
                        logger.debug(
                            "[OPENPROVIDER_PREMIUM] aftermarket %s.%s %s: %s",
                            label, ext, provider, exc,
                        )
                        continue
                    if is_free(am) and extract_is_premium(am):
                        am = dict(am)
                        am.setdefault("name", label)
                        am.setdefault("extension", ext)
                        am.setdefault("domain", f"{label}.{ext}")
                        am["_premium_provider"] = provider
                        return am
                return None

        found = await asyncio.gather(*[_one(ext) for ext in _AFTERMARKET_CHECK_EXTS])
        return [x for x in found if x]

    async def _run_scan() -> list[dict[str, Any]]:
        registry_results, aftermarket = await asyncio.gather(
            _registry_scan(), _aftermarket_scan(), return_exceptions=True,
        )
        combined: list[dict[str, Any]] = []
        for part, source in ((registry_results, "registry"), (aftermarket, "aftermarket")):
            if isinstance(part, Exception):
                logger.warning(
                    "[OPENPROVIDER_PREMIUM] %s scan failed for %s: %s",
                    source, label, part,
                )
                continue
            combined.extend(part)
        return combined

    # Hard timeout so the endpoint never hangs. Timed-out scans are NOT
    # cached, so a retry gets a fresh attempt instead of a stale empty list.
    timed_out = False
    try:
        raw = await asyncio.wait_for(_run_scan(), timeout=_PREMIUM_HARD_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        logger.warning(
            "[OPENPROVIDER_PREMIUM] scan timed out after %ss for %s",
            _PREMIUM_HARD_TIMEOUT_SEC, label,
        )
        raw = []
        timed_out = True

    # Filter to premium + available only, deduplicate by domain.
    results_by_domain: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if not (is_free(entry) and extract_is_premium(entry)):
            continue
        domain = (
            entry.get("domain")
            or f"{entry.get('name') or label}.{entry.get('extension') or ''}"
        )
        if not domain or domain.endswith("."):
            continue
        if domain not in results_by_domain:
            results_by_domain[domain] = dict(entry)

    final_list = list(results_by_domain.values())
    if not timed_out:
        _AFTERMARKET_PREMIUM_CACHE[cache_key] = (now, [dict(x) for x in final_list])
    logger.info(
        "[OPENPROVIDER_PREMIUM] completed for %s: %s premium domains found (timed_out=%s)",
        label, len(final_list), timed_out,
    )
    return final_list


def _premium_create_price(check_result: dict[str, Any]) -> float:
    """
    Return the registry-premium create price from ``premium.price.create`` only.

    IMPORTANT: Do NOT fall back to the standard reseller/product price.
    The reseller price is present for every TLD (available or taken) and
    reflects the TLD's standard pricing tier — it is NOT a signal that a
    specific domain name is available for first-time registration.

    Only an explicit ``premium.price.create > 0`` means OpenProvider has
    earmarked this exact name as an available registry-premium domain.
    Absent or zero means the domain is taken (even if is_premium=True,
    because the TLD tier is premium but this name is already registered).
    """
    premium = check_result.get("premium") or {}
    if isinstance(premium, dict):
        prem_price = premium.get("price") or {}
        if isinstance(prem_price, dict) and prem_price.get("create") is not None:
            try:
                val = float(prem_price["create"])
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
    return 0.0


def is_free(check_result: dict[str, Any]) -> bool:
    """
    True when the domain can be registered via OpenProvider.

    OpenProvider ``domains/check`` documents status values ``free``, ``reserved``,
    and ``in use``. Available domains (standard or premium) return ``status="free"``.
    ``status="active"`` with ``reason`` such as ``Domain exists`` or ``In use`` means
    the name is taken — even when ``is_premium=true`` and a TLD/reseller price is present.

    Do **not** treat ``status="active"`` + ``premium.price.create`` as available; that
    pattern includes taken registry-premium names (e.g. hustler.online / hustler.club).
    """
    status = str(check_result.get("status", "")).lower().strip()
    if status in ("free", "available"):
        return True
    if status in ("registered", "taken", "blocked", "reserved", "active"):
        return False
    return False


def extract_reseller_price(check_result: dict[str, Any]) -> float:
    unit, _currency = extract_reseller_price_details(check_result)
    return unit


def _panel_inr_create_price(quote: dict[str, Any], reseller_inr: float) -> float | None:
    """
    Optional uplift when OPENPROVIDER_PANEL_INR_FACTOR > 1.0.

    Historically used to approximate OpenProvider control-panel INR when the API
    reseller block understated panel FX for USD/EUR/GBP products. Default factor
    is 1.0 (disabled) so displayed/checkout prices equal API reseller INR plus
    admin commission only — no hidden markup.
    """
    from app.core.config import settings

    factor = settings.OPENPROVIDER_PANEL_INR_FACTOR
    if factor <= 1.0:
        return None

    price_block = quote.get("price") or {}
    if not isinstance(price_block, dict):
        return None
    product = price_block.get("product") or {}
    reseller = price_block.get("reseller") or {}
    if not isinstance(product, dict) or not isinstance(reseller, dict):
        return None
    if str(reseller.get("currency") or "").upper() != "INR":
        return None
    prod_cur = str(product.get("currency") or "").upper()
    if prod_cur not in ("USD", "EUR", "GBP"):
        return None
    try:
        prod_price = float(product.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if prod_price <= 0:
        return None
    # Panel historically showed whole rupees, rounded down.
    return math.floor(reseller_inr * factor)


def extract_create_price_details(
    quote: dict[str, Any],
    *,
    source_hint: str | None = None,
) -> tuple[float, str | None, str]:
    """
    Per-year create price for display and checkout.

    Uses OpenProvider reseller INR by default. An optional panel-INR uplift is
    applied only when OPENPROVIDER_PANEL_INR_FACTOR > 1.0.
    """
    unit, currency = extract_reseller_price_details(quote)
    tag = source_hint or (
        "openprovider_prices"
        if quote.get("tier_price") is not None or "is_promotion" in quote
        else "openprovider_check"
    )
    panel_inr = _panel_inr_create_price(quote, unit)
    if panel_inr is not None and panel_inr > 0:
        unit = panel_inr
        if tag == "openprovider_prices":
            tag = "openprovider_panel_inr"
        elif tag == "openprovider_check":
            tag = "openprovider_check_panel_inr"
    return unit, currency, tag


def extract_is_premium(payload: dict[str, Any] | None) -> bool:
    """True when OpenProvider marks the domain as registry premium."""
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("is_premium"))


def extract_reseller_price_details(
    check_result: dict[str, Any],
) -> tuple[float, str | None]:
    """
    Unit price and currency from OpenProvider.

    OpenProvider support: bill via ``price.reseller`` (then product). The
    ``is_premium`` flag is independent — do not prefer ``premium.price.create``
    over reseller when both exist. Fall back to ``premium.price.create`` only
    when reseller/product are missing.
    """
    price_block = check_result.get("price") or {}
    currency: str | None = None
    if isinstance(price_block, dict):
        reseller = price_block.get("reseller") or {}
        if isinstance(reseller, dict):
            if reseller.get("currency"):
                currency = str(reseller["currency"]).upper()
            if reseller.get("price") is not None:
                return float(reseller["price"]), currency
        product = price_block.get("product") or {}
        if isinstance(product, dict):
            if product.get("currency") and not currency:
                currency = str(product["currency"]).upper()
            if product.get("price") is not None:
                return float(product["price"]), currency
    premium = check_result.get("premium") or {}
    if isinstance(premium, dict):
        prem_price = premium.get("price") or {}
        if isinstance(prem_price, dict) and prem_price.get("create") is not None:
            return float(prem_price["create"]), currency
    return 0.0, currency


def extract_renewal_price_details(
    check_result: dict[str, Any],
) -> tuple[float | None, str | None]:
    """
    Renewal unit price and currency from OpenProvider check result.

    Only extracts explicit 'renew' keys from reseller, product, price_block,
    or premium.price. If OpenProvider omits an explicit 'renew' key in the check response
    (e.g. for 1st-year aftermarket/registry premium domains), returns None so the caller
    fetches OpenProvider's actual renewal price via GetPrice (operation='renew').
    NEVER re-uses 1st-year registration/create price as the renewal price.
    """
    price_block = check_result.get("price") or {}
    currency: str | None = None
    if isinstance(price_block, dict):
        reseller = price_block.get("reseller") or {}
        if isinstance(reseller, dict):
            if reseller.get("currency"):
                currency = str(reseller["currency"]).upper()
            if reseller.get("renew") is not None:
                try:
                    val = float(reseller["renew"])
                    if val > 0:
                        return val, currency
                except (TypeError, ValueError):
                    pass

        product = price_block.get("product") or {}
        if isinstance(product, dict):
            if product.get("currency") and not currency:
                currency = str(product["currency"]).upper()
            if product.get("renew") is not None:
                try:
                    val = float(product["renew"])
                    if val > 0:
                        return val, currency
                except (TypeError, ValueError):
                    pass

        if price_block.get("renew") is not None:
            try:
                val = float(price_block["renew"])
                if val > 0:
                    return val, currency
            except (TypeError, ValueError):
                pass

    premium = check_result.get("premium") or {}
    if isinstance(premium, dict):
        prem_price = premium.get("price")
        if isinstance(prem_price, dict):
            raw_renew = prem_price.get("renew")
            if raw_renew is not None:
                try:
                    val = float(raw_renew)
                    if val > 0:
                        return val, currency
                except (TypeError, ValueError):
                    pass

    return None, currency


def extract_getprice_renewal_details(
    quote: dict[str, Any],
) -> tuple[float | None, str | None]:
    """
    Renewal unit price from ``GET /v1beta/domains/prices`` with ``operation=renew``.

    GetPrice renew responses expose the renewal amount in ``price.reseller.price``
    (there is no separate ``renew`` sub-key). This helper reads that block only and
    never falls back to ``premium.price.create`` or registration/create pricing.
    """
    explicit, currency = extract_renewal_price_details(quote)
    if explicit is not None and explicit > 0:
        return explicit, currency

    price_block = quote.get("price") or {}
    if not isinstance(price_block, dict):
        return None, currency

    reseller = price_block.get("reseller") or {}
    if isinstance(reseller, dict):
        if reseller.get("currency"):
            currency = str(reseller["currency"]).upper()
        if reseller.get("price") is not None:
            try:
                val = float(reseller["price"])
                if val > 0:
                    return val, currency
            except (TypeError, ValueError):
                pass

    product = price_block.get("product") or {}
    if isinstance(product, dict):
        if product.get("currency") and not currency:
            currency = str(product["currency"]).upper()
        if product.get("price") is not None:
            try:
                val = float(product["price"])
                if val > 0:
                    return val, currency
            except (TypeError, ValueError):
                pass

    return None, currency


# Registry-enforced minimum create periods (years).
# Prefer live OpenProvider ``GET /v1beta/tlds/{name}`` ``min_period`` (cached).
# Fallback map covers known multi-year TLDs when the TLD API is unavailable.
# OpenProvider ``domains/check`` with_price returns the **full minimum-period
# create total** for these TLDs (verified live: .ai check == prices?period=2,
# while prices?period=1 is half that). Storefront must normalize to 1-year.
_TLD_MIN_REGISTRATION_YEARS: dict[str, int] = {
    "ai": 2,
}
_TLD_MIN_PERIOD_CACHE: dict[str, int] = {}


def _normalize_tld_ext(extension_no_dot: str) -> str:
    return (extension_no_dot or "").lower().lstrip(".")


def _parse_tld_min_period(data: dict[str, Any] | None) -> int | None:
    """Extract ``min_period`` (years) from an OpenProvider TLD payload."""
    if not isinstance(data, dict):
        return None
    for key in ("min_period", "minPeriod", "min_period_years", "minPeriodYears"):
        raw = data.get(key)
        if raw is None:
            continue
        try:
            years = int(raw)
        except (TypeError, ValueError):
            continue
        if years >= 1:
            return years
    return None


def tld_min_registration_years(extension_no_dot: str) -> int:
    """Minimum registration period in years for a TLD (API cache → fallback map → 1)."""
    ext = _normalize_tld_ext(extension_no_dot)
    if not ext:
        return 1
    if ext in _TLD_MIN_PERIOD_CACHE:
        return max(1, int(_TLD_MIN_PERIOD_CACHE[ext]))
    return max(1, int(_TLD_MIN_REGISTRATION_YEARS.get(ext, 1)))


def resolve_registration_period(requested: int, extension_no_dot: str) -> int:
    """Clamp requested period up to the TLD registry minimum (e.g. .ai → 2)."""
    return max(1, int(requested or 1), tld_min_registration_years(extension_no_dot))


async def ensure_tld_min_period(extension_no_dot: str) -> int:
    """
    Resolve minimum registration years from OpenProvider TLD ``min_period``.

    Caches the result for subsequent sync lookups (check / cart / quote).
    Pricing math is unchanged — only the source of the minimum period improves.
    """
    ext = _normalize_tld_ext(extension_no_dot)
    if not ext:
        return 1
    if ext in _TLD_MIN_PERIOD_CACHE:
        return max(1, int(_TLD_MIN_PERIOD_CACHE[ext]))
    try:
        data = await get_tld(ext)
        parsed = _parse_tld_min_period(data)
        if parsed is not None:
            _TLD_MIN_PERIOD_CACHE[ext] = parsed
            return parsed
    except Exception as exc:
        logger.warning(
            "[OPENPROVIDER_TLD] Could not load min_period for .%s: %s",
            ext,
            exc,
        )
    fallback = max(1, int(_TLD_MIN_REGISTRATION_YEARS.get(ext, 1)))
    return fallback


def yearly_create_price_from_check(raw_price: float, extension_no_dot: str) -> float:
    """
    Normalize OpenProvider check/list create prices to a **1-year** unit.

    For TLDs with a multi-year minimum (e.g. .ai), ``domains/check`` with_price
    returns the full minimum-period total. Storefront display and cart base
    prices must stay 1-year; multi-year totals are quoted only at cart/checkout
    via ``domains/prices?period=N``.
    """
    price = float(raw_price or 0)
    if price <= 0:
        return 0.0
    years = tld_min_registration_years(extension_no_dot)
    if years <= 1:
        return round(price, 2)
    return round(price / years, 2)



def friendly_error_from_body(raw: str) -> str:
    if not raw:
        return "Domain registration failed. Try again or contact support."
    lower = raw.lower()
    if "insufficient" in lower or '"code":920' in raw:
        cp = control_panel_url()
        return (
            f"Registration balance is too low. Add funds at {cp}, "
            "then retry."
        )
    if "invalid period" in lower:
        return "This extension requires a longer registration period."
    match = re.search(r'"desc"\s*:\s*"([^"]+)"', raw)
    if match:
        return f"{match.group(1)}"
    
    if raw.startswith("OpenProvider:") or raw.startswith("OpenProvider reseller balance"):
        return "Domain registration failed. Please try again or contact HubRegistrar support."

    return "Domain registration failed."


async def create_customer(contact: dict[str, Any]) -> str:
    logger.info("[OPENPROVIDER_REGISTRATION] Creating customer contact for email: %s", contact.get("email"))
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/customers",
            headers=headers,
            json=contact,
        )
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_REGISTRATION] Create customer contact HTTP %s: %s", resp.status_code, resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        body = resp.json()

    if body.get("code") != 0:
        logger.error("[OPENPROVIDER_REGISTRATION] Create customer contact rejected: %s", body)
        raise RuntimeError(friendly_error_from_body(str(body)))
    handle = str(body["data"]["handle"])
    logger.info("[OPENPROVIDER_REGISTRATION] Contact handle created successfully: %s", handle)
    return handle


async def get_customer(handle: str) -> dict[str, Any]:
    """Read-only ``GET /v1beta/customers/{handle}``. Empty dict on failure."""
    from urllib.parse import quote

    cleaned = (handle or "").strip()
    if not cleaned:
        return {}
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/customers/{quote(cleaned, safe='')}",
            headers=headers,
        )
    if resp.status_code >= 400:
        logger.warning(
            "OpenProvider get customer HTTP %s handle=%s",
            resp.status_code,
            cleaned,
        )
        return {}
    try:
        body = resp.json()
    except json.JSONDecodeError:
        return {}
    if body.get("code") != 0:
        return {}
    data = body.get("data")
    return data if isinstance(data, dict) else {}


_TLD_INFO_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TLD_INFO_TTL_SEC = 3600.0


async def get_tld(extension_no_dot: str) -> dict[str, Any]:
    """Official ``GET /v1beta/tlds/{name}`` — TLD capabilities (WHOIS privacy, DNSSEC, etc.)."""
    ext = _normalize_tld_ext(extension_no_dot)
    if not ext:
        return {}
    now = time.time()
    cached = _TLD_INFO_CACHE.get(ext)
    if cached and (now - cached[0]) < _TLD_INFO_TTL_SEC:
        return cached[1]

    headers = await _auth_headers()
    async with _op_http_client(timeout=20.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/tlds/{ext}",
            headers=headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(f"tlds/{ext}", resp.status_code, resp.text or "")
            )
        body = resp.json()
    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"Registrar tlds error: {desc}")
    data = body.get("data")
    result = data if isinstance(data, dict) else {}
    _TLD_INFO_CACHE[ext] = (now, result)
    parsed = _parse_tld_min_period(result)
    if parsed is not None:
        _TLD_MIN_PERIOD_CACHE[ext] = parsed
    return result


async def is_private_whois_allowed(extension_no_dot: str) -> bool:
    """True when OpenProvider allows WHOIS privacy for this TLD."""
    try:
        data = await get_tld(extension_no_dot)
    except Exception as exc:
        logger.warning(
            "[OPENPROVIDER_WHOIS] Could not load TLD %s for privacy flag: %s",
            extension_no_dot,
            exc,
        )
        return False
    return bool(data.get("is_private_whois_allowed"))


async def register_domain(
    name: str,
    extension_no_dot: str,
    handle: str,
    period_years: int,
    *,
    contact: dict[str, Any] | None = None,
    is_private_whois_enabled: bool | None = None,
) -> dict[str, Any]:
    logger.info(
        "[OPENPROVIDER_REGISTRATION] Starting registration for %s.%s, handle: %s, period: %d years whois_privacy=%s",
        name,
        extension_no_dot,
        handle,
        period_years,
        is_private_whois_enabled,
    )
    name_servers = [{"name": ns} for ns in default_nameservers()]

    payload: dict[str, Any] = {
        "owner_handle": handle,
        "admin_handle": handle,
        "tech_handle": handle,
        "billing_handle": handle,
        "domain": {"name": name, "extension": extension_no_dot},
        "period": period_years,
        "autorenew": "default",
        "name_servers": name_servers,
    }
    if is_private_whois_enabled is not None:
        payload["is_private_whois_enabled"] = bool(is_private_whois_enabled)

    headers = await _auth_headers()
    url = f"{_base_url()}/v1beta/domains"
    logger.info(
        "[OPENPROVIDER_REGISTRATION] Request sent POST %s domain=%s.%s period=%s",
        url,
        name,
        extension_no_dot,
        period_years,
    )
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            url,
            headers=headers,
            json=payload,
        )
        logger.info(
            "[OPENPROVIDER_REGISTRATION] Response received HTTP %s domain=%s.%s body_len=%s",
            resp.status_code,
            name,
            extension_no_dot,
            len(resp.text or ""),
        )
        if resp.status_code >= 400:
            logger.error(
                "[OPENPROVIDER_REGISTRATION] Registration failed HTTP %s domain=%s.%s body=%s",
                resp.status_code,
                name,
                extension_no_dot,
                resp.text,
            )
            raise RuntimeError(friendly_error_from_body(resp.text))
        body = resp.json()

    if body.get("code") != 0:
        logger.error(
            "[OPENPROVIDER_REGISTRATION] Registration rejected domain=%s.%s body=%s",
            name,
            extension_no_dot,
            body,
        )
        raise RuntimeError(friendly_error_from_body(str(body)))

    data = body["data"]
    # Inject nameservers details for compatibility with checkout/provisioning flow
    data["nameservers"] = [ns["name"] for ns in name_servers]
    data["nameserverSource"] = "openprovider"
    logger.info(
        "[OPENPROVIDER_REGISTRATION] Registration success domain=%s.%s data=%s",
        name,
        extension_no_dot,
        data,
    )
    return data


def validate_runtime(for_live_checkout: bool = False) -> dict:
    sandbox = is_sandbox()
    blocking = []
    warnings = []

    if not is_configured():
        blocking.append("OpenProvider credentials missing (OPENPROVIDER_USERNAME and OPENPROVIDER_PASSWORD).")

    nameservers = _default_nameservers()
    if len(nameservers) < 2:
        blocking.append("OpenProvider default nameservers missing or misconfigured in OPENPROVIDER_DEFAULT_NAMESERVERS.")

    if for_live_checkout or not sandbox:
        rzp_key = settings.resolved_razorpay_key_id()
        if rzp_key.startswith("rzp_test_"):
            blocking.append(
                "OpenProvider is not correctly configured for live checkout: Razorpay test keys (rzp_test_*) "
                "cannot be used with OPENPROVIDER_USE_SANDBOX=false. Set RAZORPAY_LIVE_KEY_ID=rzp_live_* "
                "(or RAZORPAY_KEY_ID) for real payments."
            )
        if not settings.resolved_razorpay_webhook_secret():
            warnings.append(
                "RAZORPAY_WEBHOOK_SECRET not set — checkout uses payment verify only."
            )
        if not settings.resolved_razorpay_key_id() or not settings.resolved_razorpay_key_secret():
            blocking.append("Razorpay KEY_ID / KEY_SECRET missing.")

    if sandbox and for_live_checkout:
        blocking.append(
            "Cannot run live-money checkout while OPENPROVIDER_USE_SANDBOX=true. "
            "Set OPENPROVIDER_USE_SANDBOX=false with live credentials."
        )

    profile = {
        "env": "sandbox" if sandbox else "live",
        "sandbox": sandbox,
        "apiBaseUrl": _base_url(),
        "controlPanelUrl": control_panel_url(),
        "configured": is_configured(),
    }

    return {
        "profile": profile,
        "sandbox": sandbox,
        "invoiceOptionEffective": None,
        "nameservers": nameservers,
        "ready": len(blocking) == 0,
        "blockingIssues": blocking,
        "warnings": warnings,
    }



async def get_domain_all_details(domain_id: str) -> dict:
    logger.info("[OPENPROVIDER_REGISTRATION] Fetching all details for domain ID: %s", domain_id)
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/domains/{domain_id}",
            headers=headers,
            params={"with_verification_email": "true"},
        )
        if resp.status_code >= 400:
            logger.error(
                "[OPENPROVIDER_REGISTRATION] Get domain details HTTP %s: %s",
                resp.status_code,
                (resp.text or "")[:800],
            )
            raise RuntimeError(
                _format_http_error(f"domains/{domain_id}", resp.status_code, resp.text or "")
            )
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Registrar domains detail returned invalid JSON.") from exc

    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        logger.error("[OPENPROVIDER_REGISTRATION] Get domain details rejected: %s", desc)
        raise RuntimeError(f"Registrar domains detail error: {desc}")

    data = body.get("data") or {}
    logger.info("[OPENPROVIDER_REGISTRATION] Get domain details response: %s", data)
    return data


def _fqdn_from_domain_list_item(item: dict[str, Any]) -> str | None:
    """OpenProvider list/get domain objects nest SLD+TLD under ``domain``."""
    if not isinstance(item, dict):
        return None
    full = str(item.get("full_name") or "").strip()
    if full:
        return full.lower().rstrip(".")
    nested = item.get("domain") if isinstance(item.get("domain"), dict) else {}
    name = str((nested or {}).get("name") or item.get("name") or "").strip()
    ext = str((nested or {}).get("extension") or item.get("extension") or "").strip().lstrip(".")
    if name and ext:
        if name.lower().endswith("." + ext.lower()):
            return name.lower()
        return f"{name}.{ext}".lower()
    if name and "." in name:
        return name.lower()
    return None


def _domain_record_from_search_results(fqdn: str, results: list) -> dict[str, Any] | None:
    want = fqdn.lower().strip().rstrip(".")
    if not isinstance(results, list):
        return None
    for item in results:
        if not isinstance(item, dict):
            continue
        got = _fqdn_from_domain_list_item(item)
        if got == want and item.get("id") is not None:
            return item
    return None


def _domain_id_from_search_results(fqdn: str, results: list) -> str | None:
    record = _domain_record_from_search_results(fqdn, results)
    if not record:
        return None
    domain_id = record.get("id")
    return str(domain_id) if domain_id is not None else None


def _lookup_domain_query_variants(fqdn_n: str) -> list[dict[str, Any]]:
    """OpenProvider ``domain_name_pattern`` is the SLD only, not the FQDN.

    Use ``full_name`` for an exact match, then SLD + extension.
    """
    common = {"with_verification_email": "true", "limit": 50}
    variants: list[dict[str, Any]] = [{"full_name": fqdn_n, **common}]
    if "." in fqdn_n:
        name, ext = fqdn_n.split(".", 1)
        variants.append({**common, "domain_name_pattern": name, "extension": ext})
    else:
        variants.append({**common, "domain_name_pattern": fqdn_n})
    return variants


async def lookup_domain_record_by_fqdn(fqdn: str) -> dict[str, Any] | None:
    """Return the reseller domain list/get record for an exact FQDN, if any."""
    fqdn_n = fqdn.lower().strip().rstrip(".")
    if not fqdn_n:
        return None
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        for params in _lookup_domain_query_variants(fqdn_n):
            resp = await client.get(
                f"{_base_url()}/v1beta/domains",
                headers=headers,
                params=params,
            )
            if resp.status_code >= 400:
                logger.error(
                    "OpenProvider search domains HTTP %s: %s",
                    resp.status_code,
                    (resp.text or "")[:800],
                )
                continue
            try:
                body = resp.json()
            except json.JSONDecodeError:
                continue
            if body.get("code") != 0:
                continue
            results = (body.get("data") or {}).get("results") or []
            found = _domain_record_from_search_results(fqdn_n, results)
            if found:
                logger.info(
                    "OpenProvider domain lookup hit fqdn=%s provider_domain_id=%s "
                    "status=%s owner_handle_set=%s verification_email_name_set=%s "
                    "result_keys=%s",
                    fqdn_n,
                    found.get("id"),
                    found.get("status"),
                    bool(found.get("owner_handle")),
                    bool(str(found.get("verification_email_name") or "").strip()),
                    sorted(found.keys()),
                )
                return found
            if results:
                sample = results[0] if isinstance(results[0], dict) else {}
                logger.warning(
                    "OpenProvider domain search no FQDN match fqdn=%s "
                    "result_count=%s sample_keys=%s",
                    fqdn_n,
                    len(results),
                    sorted(sample.keys()) if isinstance(sample, dict) else [],
                )
    return None


async def lookup_order_id_by_domain(fqdn: str) -> str | None:
    record = await lookup_domain_record_by_fqdn(fqdn)
    if not record:
        return None
    domain_id = record.get("id")
    return str(domain_id) if domain_id is not None else None


async def resend_raa_verification(*, email: str, handle: str) -> bool:
    logger.info("[OPENPROVIDER_REGISTRATION] Resending RAA email verification for email: %s, handle: %s", email, handle)
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/customers/verifications/emails/restart",
            headers=headers,
            json={
                "email": email.strip(),
            },
        )
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_REGISTRATION] Resend verification HTTP %s: %s", resp.status_code, resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        body = resp.json()

    if body.get("code") != 0:
        logger.error("[OPENPROVIDER_REGISTRATION] Resend verification rejected: %s", body)
        raise RuntimeError(friendly_error_from_body(str(body)))

    logger.info("[OPENPROVIDER_REGISTRATION] Resend verification request accepted.")
    return True


async def check_availability_bulk(label: str, tlds: list[str]) -> list[dict]:
    headers = await _auth_headers()
    logger.info("[OPENPROVIDER_AVAILABILITY] Bulk checking availability for label: %s, TLDs: %s", label, tlds)
    domains_payload = [{"name": label, "extension": tld.lstrip(".")} for tld in tlds]
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/domains/check",
            headers=headers,
            json={
                "domains": domains_payload,
                "with_price": True,
            },
        )
        if resp.status_code >= 400:
            logger.error(
                "[OPENPROVIDER_AVAILABILITY] Bulk check HTTP %s: %s",
                resp.status_code,
                (resp.text or "")[:800],
            )
            raise RuntimeError(
                _format_http_error("domains/check", resp.status_code, resp.text or "")
            )
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Registrar domains/check returned invalid JSON.") from exc

    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"OpenProvider domains/check error: {desc}")

    results = body.get("data", {}).get("results", [])
    logger.info("[OPENPROVIDER_AVAILABILITY] Bulk check response: %s", results)
    mapped_results = []
    for entry in results:
        fqdn = entry.get("domain")
        if not fqdn:
            name = entry.get("name")
            ext = entry.get("extension")
            if name and ext:
                fqdn = f"{name}.{ext}"
            else:
                fqdn = ""
        is_avail = is_free(entry)
        mapped_results.append({
            "domain": fqdn,
            "status": "available" if is_avail else "taken",
            "classkey": None,
            "attributes": entry,
        })
    return mapped_results


async def list_active_tlds(limit: int = 1000, offset: int = 0) -> list[str]:
    """
    Return the COMPLETE list of active TLD extensions offered by OpenProvider.

    No hardcoded/whitelisted subset — this pulls every extension with
    status=ACT directly from the registrar so the storefront can offer all of
    them. Supports pagination via limit/offset (max 1000 per page).
    """
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        # NOTE: do NOT send `only_names=true` — OpenProvider's /tlds endpoint
        # returns HTTP 500 (code=299 "An unknown error has occurred") for that
        # parameter, which previously crashed the whole catalog fetch and left
        # the storefront with no (or a hardcoded) TLD list. The full record set
        # is returned and we extract the `name` field ourselves.
        resp = await client.get(
            f"{_base_url()}/v1beta/tlds",
            headers=headers,
            params={
                "status": "ACT",
                "limit": limit,
                "offset": offset,
            },
        )
        if resp.status_code >= 400:
            logger.error(
                "[OPENPROVIDER_TLDS] List tlds failed HTTP %s: %s",
                resp.status_code,
                (resp.text or "")[:800],
            )
            raise RuntimeError(
                _format_http_error("tlds", resp.status_code, resp.text or "")
            )
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Registrar tlds returned invalid JSON.") from exc

    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"Registrar tlds error: {desc}")

    # Raw response logging: verify the backend received the full TLD catalog
    # from OpenProvider before any processing/filtering.
    results = body.get("data", {}).get("results", [])
    logger.info(
        "[OPENPROVIDER_TLDS_RAW] offset=%s limit=%s returned=%s sample_names=%s",
        offset,
        limit,
        len(results),
        [r.get("name") for r in results[:15] if isinstance(r, dict)],
    )
    # Each result is a dict with a `name` field (the extension). Flatten to the
    # bare extension names OpenProvider uses in /domains/check.
    names = [str(r.get("name")) for r in results if isinstance(r, dict) and r.get("name")]
    return names


_PRIORITY_TLDS = [
    "com", "net", "org", "in", "co", "io", "ai", "me", "info", "biz",
    "xyz", "online", "site", "tech", "store", "shop", "app", "dev", "page", "web",
    "blog", "club", "live", "fun", "fyi", "icu", "bond", "cyou", "lol", "monster",
    "cloud", "host", "website", "space", "world", "link", "click", "top", "vip", "pro", "mobi", "tel",
    "asia", "name", "aero", "cat", "jobs", "travel", "xxx", "ooo", "men", "win",
    "bid", "loan", "date", "review", "trade", "webcam", "download", "racing", "party",
    "cricket", "faith", "science", "accountant", "certificate", "credit", "finance",
    "gripe", "hosting", "insure", "investments", "lawyer", "loans", "money", "mortgage",
    "partners", "properties", "reise", "repair", "report", "salon", "schule", "singles",
    "social", "solar", "solutions", "supplies", "supply", "systems", "tattoo", "tienda",
    "tips", "today", "tools", "town", "training", "tv", "university", "vacations",
    "ventures", "viajes", "villas", "vision", "vodka", "voyage", "watch", "wine", "works",
    "yoga", "zone", "buzz", "design", "digital", "email", "graphics", "guide", "guru",
    "help", "house", "light", "london", "media", "news", "ninja", "photography", "pics",
    "pictures", "rocks", "shiksha", "soccer", "studio", "style", "team", "technology",
    "tube", "uno", "vacations", "wiki", "wtf", "zone", "codes", "coffee", "codes",
    "company", "computer", "construction", "consulting", "contact", "contractors",
    "cool", "coupons", "cruises", "dance", "dating", "deals", "delivery", "democrat",
    "dental", "diamonds", "directory", "discount", "dog", "domains", "education",
    "energy", "engineer", "enterprises", "equipment", "estate", "events", "exchange",
    "exposed", "express", "fail", "farm", "finance", "fitness", "flights", "florist",
    "football", "forsale", "foundation", "fund", "furniture", "gallery", "games", "gifts",
    "gives", "glass", "global", "golf", "graphics", "green", "guitars", "guru", "health",
    "hockey", "holdings", "holiday", "homes", "horse", "house", "immo", "industries",
    "institute", "international", "irish", "jetzt", "kaufen", "kitchen", "land", "lease",
    "legal", "lgbt", "life", "limited", "limo", "link", "live", "loans", "lol", "maison",
    "management", "market", "marketing", "mba", "media", "memorial", "moda", "mom",
    "movie", "nagoya", "network", "ngo", "okinawa", "ong", "ong", "organic", "partners",
    "parts", "pet", "pharmacy", "photo", "photos", "pictures", "pink", "place", "plumbing",
    "plus", "poker", "porn", "press", "productions", "properties", "pub", "racing",
    "recipes", "rehab", "rent", "repair", "report", "republican", "restaurant", "reviews",
    "rip", "rocks", "rodeo", "run", "ryukyu", "sale", "school", "schule", "services",
    "sexy", "shoes", "show", "singles", "social", "software", "solar", "solutions",
    "stream", "studio", "style", "supplies", "supply", "support", "surf", "surgery",
    "systems", "tax", "taxi", "team", "technology", "tel", "tennis", "theater", "tienda",
    "tips", "tires", "today", "tools", "tours", "town", "toys", "trade", "training",
    "travel", "tube", "university", "uno", "vacations", "ventures", "viajes", "video",
    "villas", "vision", "vodka", "voyage", "watch", "webcam", "wiki", "wine", "works",
    "wtf", "xxx", "yoga", "zone",
]


# Provider-safe batching for TLD label search (/domains/check). OpenProvider
# accepts bulk availability checks of up to 100 domains per request, so each
# search request carries a full batch of TLDs (never one TLD per request). The
# full active-TLD catalog is checked across a small number of parallel batches
# (bounded by the concurrency semaphore), keeping searches fast while still
# allowing a single unpriceable extension to be isolated and dropped via
# binary-split.
_DOMAIN_SEARCH_BATCH_SIZE = 30
_DOMAIN_SEARCH_CONCURRENCY = 6
_DOMAIN_SEARCH_RETRIES = 4
# Error codes that poison the entire batch (one bad TLD fails all siblings).
_DOMAIN_CHECK_POISON_CODES = frozenset({199, 701})


async def list_all_active_tlds(limit: int = 1000, offset: int = 0) -> list[str]:
    """
    Return every active TLD offered by OpenProvider (full catalog, paginated).

    Kept as a stable entry point used by search/dashboard code and tests; it
    mirrors :func:`list_active_tlds`, pulling all ``status=ACT`` extensions.
    """
    return await list_active_tlds(limit=limit, offset=offset)


async def _get_active_tlds_cached(limit: int = 600) -> list[str]:
    """Return the active-TLD catalog, cached in-process for ``_TLD_CATALOG_TTL_SECONDS``.

    Falls through to a live ``list_active_tlds`` fetch when the cache is cold,
    stale, or when ``list_active_tlds`` has been replaced (e.g. by a test mock).
    An empty result is never cached so a transient registrar hiccup doesn't
    poison the cache.
    """
    global _tld_catalog_cache, _tld_catalog_expiry, _tld_catalog_src_id
    now = time.time()
    fn_id = id(list_active_tlds)
    if (
        _tld_catalog_cache is not None
        and now < _tld_catalog_expiry
        and _tld_catalog_src_id == fn_id
    ):
        return _tld_catalog_cache

    catalog = await list_active_tlds(limit=limit, offset=0)
    if catalog:
        _tld_catalog_cache = list(catalog)
        _tld_catalog_expiry = now + _TLD_CATALOG_TTL_SECONDS
        _tld_catalog_src_id = fn_id
    return catalog


async def _resolve_tlds_to_check(label: str, max_tlds: int = 200) -> list[str]:
    """
    Resolve the full list of TLD extensions to check for a label.

    Prefers the full active-TLD catalog from OpenProvider (no whitelist). When
    the catalog fetch yields nothing (e.g. unconfigured / offline), falls back
    to the curated priority list so searches still work for common TLDs.
    """
    label = _sanitize_search_label(label)

    catalog: list[str] = []
    try:
        # Fetch up to 600 active TLDs to avoid processing 1500+ domains per search,
        # keeping latency reasonable while still offering a massive catalog. The
        # catalog is cached in-process so this is a no-op on the hot path.
        catalog = await _get_active_tlds_cached(limit=600)
    except Exception as exc:
        logger.warning("[OPENPROVIDER_SEARCH] Catalog fetch failed for %s: %s", label, exc)
    if catalog:
        tlds = [t.lstrip(".") for t in catalog]
        tlds = tlds[:600]
    else:
        tlds = [t.lstrip(".") for t in _PRIORITY_TLDS[:min(600, max(1, max_tlds))]]
    # De-duplicate while preserving order (the priority list contains repeats).
    seen: set[str] = set()
    deduped: list[str] = []
    for tld in tlds:
        if tld and tld not in seen:
            seen.add(tld)
            deduped.append(tld)
    return deduped


async def _check_tld_batches(
    label: str,
    tlds_to_check: list[str],
    *,
    provider: str | None = None,
    concurrency: int | None = None,
    max_retries: int | None = None,
) -> list[dict[str, Any]]:
    """
    Run provider-safe batched availability checks for the given TLD list.

    The TLDs are split into batches of ``_DOMAIN_SEARCH_BATCH_SIZE`` and run
    concurrently with a bounded semaphore (``_DOMAIN_SEARCH_CONCURRENCY``) so the
    search completes in a handful of parallel requests instead of one request per
    TLD. Transient throttles (5xx, code=10005) are retried; a "poison" batch (one
    extension fails the whole request, e.g. code=199/701) is isolated via
    binary-split and the bad TLD dropped rather than failing the entire search.

    ``provider`` (optional) allows registry (default), afternic, or sedo checks.
    ``concurrency``/``max_retries`` (optional) let background/secondary scans
    (e.g. the premium marketplace search) use a lighter footprint so they don't
    compete with a concurrently running foreground search for the same
    rate-limited registrar account.
    """
    if not tlds_to_check:
        return []

    import asyncio

    headers = await _auth_headers()
    BATCH = _DOMAIN_SEARCH_BATCH_SIZE
    CONCURRENCY = concurrency or _DOMAIN_SEARCH_CONCURRENCY
    MAX_RETRIES = max_retries or _DOMAIN_SEARCH_RETRIES

    total_batches = max(1, (len(tlds_to_check) + BATCH - 1) // BATCH)
    logger.info(
        "[OPENPROVIDER_SEARCH] Search plan label=%s total_tlds=%s batch_size=%s "
        "total_batches=%s concurrency=%s provider=%s",
        label, len(tlds_to_check), BATCH, total_batches, CONCURRENCY, provider or "registry",
    )

    async def _check_chunk(chunk: list[str], idx: int) -> list[dict[str, Any]]:
        domains_payload = [{"name": label, "extension": tld} for tld in chunk]
        tld_start = (idx * BATCH) + 1
        tld_end = tld_start + len(chunk) - 1
        if idx >= total_batches:
            logger.info(
                "[OPENPROVIDER_SEARCH] label=%s retry batch %s (size %s) provider=%s",
                label, idx - total_batches + 1, len(chunk), provider or "registry",
            )
        else:
            logger.info(
                "[OPENPROVIDER_SEARCH] label=%s batch %s/%s TLDs %s-%s of %s (size %s) provider=%s",
                label, idx + 1, total_batches, tld_start, tld_end, len(tlds_to_check), len(chunk), provider or "registry",
            )
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                payload: dict[str, Any] = {"domains": domains_payload, "with_price": True}
                if provider:
                    payload["provider"] = provider
                resp = await client.post(
                    f"{_base_url()}/v1beta/domains/check",
                    headers=headers,
                    json=payload,
                )
                # Auth / invalid-token: wrapper already refreshed once. Never
                # multiply failures via the transient retry loop.
                if _response_is_auth_error(resp):
                    logger.error(
                        "[OPENPROVIDER_SEARCH] domains/check authentication error "
                        "(HTTP %s). Not retrying.",
                        resp.status_code,
                    )
                    raise RuntimeError(
                        _format_http_error("domains/check", resp.status_code, resp.text or "")
                    )
                if resp.status_code >= 400:
                    is_poison = False
                    if resp.status_code == 500:
                        try:
                            body = resp.json()
                            # code=10005 "Access denied" is permanent (API IP
                            # whitelist / token-IP mismatch) — retrying only
                            # burns ~60s per search and hides the real cause.
                            if body.get("code") == 10005:
                                logger.error(
                                    "[OPENPROVIDER_SEARCH] domains/check access denied (code=10005). "
                                    "Not retrying — fix the API IP whitelist in cp.openprovider.eu "
                                    "and OPENPROVIDER_CLIENT_IP."
                                )
                                raise RuntimeError(
                                    _format_http_error("domains/check", resp.status_code, resp.text or "")
                                )
                            if body.get("code") in _DOMAIN_CHECK_POISON_CODES:
                                is_poison = True
                                desc = body.get("desc") or body.get("message") or "unknown"
                                logger.warning("[OPENPROVIDER_SEARCH] HTTP 500 on batch (size %s) with poison code %s - treating as poisoned", len(chunk), body.get("code"))
                                raise _PoisonBatchError(
                                    f"OpenProvider domains/check batch poisoned (code={body.get('code')}): {desc}",
                                    chunk=chunk,
                                )
                        except json.JSONDecodeError:
                            pass
                        except _PoisonBatchError:
                            raise

                    if resp.status_code in (429, 500, 502, 503, 504) and not is_poison:
                        batch_num = (idx - total_batches + 1) if idx >= total_batches else (idx + 1)
                        logger.warning(
                            "[OPENPROVIDER_SEARCH] Batch %s attempt %s got HTTP %s, retrying. Body: %s",
                            batch_num, attempt, resp.status_code, (resp.text or "")[:200],
                        )
                        last_err = RuntimeError(
                            _format_http_error("domains/check", resp.status_code, resp.text or "")
                        )
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    logger.error(
                        "[OPENPROVIDER_SEARCH] Bulk check failed HTTP %s: %s",
                        resp.status_code,
                        (resp.text or "")[:800],
                    )
                    raise RuntimeError(
                        _format_http_error("domains/check", resp.status_code, resp.text or "")
                    )

                try:
                    body = resp.json()
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Registrar domains/check returned invalid JSON.") from exc
                if body.get("code") != 0:
                    code = body.get("code")
                    desc = body.get("desc") or body.get("message") or "unknown"
                    # Whole-batch poison: isolate + binary-split the TLDs.
                    if code in _DOMAIN_CHECK_POISON_CODES:
                        raise _PoisonBatchError(
                            f"OpenProvider domains/check batch poisoned (code={code}): {desc}",
                            chunk=chunk,
                        )
                    raise RuntimeError(f"Registrar domains/check error: {desc}")
                return body.get("data", {}).get("results", [])
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = exc
                logger.warning(
                    "[OPENPROVIDER_SEARCH] Batch %s attempt %s transport error, retrying: %s",
                    idx // BATCH + 1, attempt, exc,
                )
                await asyncio.sleep(min(2 ** attempt, 8))
        raise RuntimeError(
            f"OpenProvider domains/check failed after {MAX_RETRIES} attempts "
            f"for batch {idx // BATCH + 1}."
        ) from last_err

    class _PoisonBatchError(RuntimeError):
        def __init__(self, message: str, *, chunk: list[str]) -> None:
            super().__init__(message)
            self.chunk = chunk

    async def _check_isolated(chunk: list[str], idx: int) -> list[dict[str, Any]]:
        """
        Check a chunk, isolating poison TLDs via binary search so a single bad
        extension cannot sink its siblings. The bad TLD is dropped silently.
        """
        try:
            return await _check_chunk(chunk, idx)
        except _PoisonBatchError as exc:
            bad_chunk = exc.chunk
            if len(bad_chunk) <= 1:
                logger.warning(
                    "[OPENPROVIDER_SEARCH] Dropping unpriceable TLD %s for %s",
                    bad_chunk[0], label,
                )
                return []
            mid = len(bad_chunk) // 2
            # Isolate the two halves CONCURRENTLY instead of sequentially. A
            # poisoned batch used to binary-split one side after the other, so a
            # single bad TLD serialised ~log2(N) round-trips (the slow tail the
            # remaining-extensions list was waiting on). Running the halves in
            # parallel collapses that to ~log2(N) depth of latency while still
            # only touching the sub-chunk that actually contains the poison.
            left, right = await asyncio.gather(
                _check_isolated(bad_chunk[:mid], idx),
                _check_isolated(bad_chunk[mid:], idx),
            )
            return left + right

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _bounded(chunk: list[str], idx: int) -> list[dict[str, Any]]:
        async with semaphore:
            return await _check_isolated(chunk, idx)

    chunks = [tlds_to_check[i : i + BATCH] for i in range(0, len(tlds_to_check), BATCH)]

    # Reuse ONE pooled HTTP client for every batch (and retry) in this search
    # instead of opening a fresh connection per batch. This keeps the TLS
    # handshake cost paid once and lets keep-alive connections be reused, which
    # noticeably speeds up multi-batch searches.
    limits = httpx.Limits(
        max_connections=max(CONCURRENCY * 2, 10),
        max_keepalive_connections=max(CONCURRENCY * 2, 10),
    )
    async with _op_http_client(timeout=90.0, limits=limits) as client:
        tasks = [_bounded(chunk, i) for i, chunk in enumerate(chunks)]
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
        raw_results: list[dict[str, Any]] = []
        failed_chunks = 0
        missing_tlds: list[str] = []
        for res, chunk in zip(chunk_results, chunks):
            if isinstance(res, Exception):
                # Auth failures must not fall through to the missing-TLD retry
                # path — that would multiply invalid-token / login attempts.
                err_l = str(res).lower()
                if (
                    "http 401" in err_l
                    or "code=196" in err_l
                    or "circuit breaker" in err_l
                    or (
                        "authentication" in err_l
                        and ("failed" in err_l or "error" in err_l or "login" in err_l)
                    )
                ):
                    logger.error(
                        "[OPENPROVIDER_SEARCH] Aborting search on authentication failure: %s",
                        res,
                    )
                    raise res
                failed_chunks += 1
                missing_tlds.extend(tld for tld in chunk)
                logger.error(
                    "[OPENPROVIDER_SEARCH] Chunk %s failed permanently: %s",
                    chunks.index(chunk) + 1,
                    res,
                )
                continue
            raw_results.extend(res)

        if missing_tlds:
            logger.warning(
                "[OPENPROVIDER_SEARCH] Retrying %s missing TLDs in batches after chunk failures",
                len(missing_tlds),
            )
            missing_chunks = [missing_tlds[i : i + BATCH] for i in range(0, len(missing_tlds), BATCH)]
            missing_tasks = [_bounded(chunk, total_batches + i) for i, chunk in enumerate(missing_chunks)]
            missing_chunk_results = await asyncio.gather(*missing_tasks, return_exceptions=True)
            for res in missing_chunk_results:
                if isinstance(res, Exception):
                    logger.error(
                        "[OPENPROVIDER_SEARCH] Missing TLD batch retry failed: %s", res
                    )
                    continue
                raw_results.extend(res)

    if failed_chunks:
        logger.warning(
            "[OPENPROVIDER_SEARCH] %s chunk(s) had failures; individual retries completed. "
            "Returning %s total results for %s",
            failed_chunks,
            len(raw_results),
            label,
        )

    # Every batch failed → surface a single error (the original behaviour: a
    # total provider outage must raise, not silently return an empty list).
    if not raw_results and failed_chunks:
        raise RuntimeError(
            f"OpenProvider domains/check failed for all {failed_chunks} batch(es) "
            f"for label {label}."
        )

    logger.info("[OPENPROVIDER_SEARCH] Bulk check returned %s TLD results for %s", len(raw_results), label)
    logger.info(
        "[OPENPROVIDER_SEARCH_RAW] label=%s total_raw_results=%s tlds=%s",
        label,
        len(raw_results),
        sorted({r.get("extension") for r in raw_results if isinstance(r, dict)}),
    )
    return raw_results


async def _check_labels_batch(
    labels: list[str],
    tlds_to_check: list[str],
    *,
    provider: str | None = None,
    concurrency: int | None = None,
    max_retries: int | None = None,
) -> list[dict[str, Any]]:
    """Provider-safe batched availability check for MANY labels at once.

    The domains/check endpoint accepts an array of ``{name, extension}`` pairs,
    so Random Premium generation checks dozens of candidate labels in a handful
    of requests instead of one request per label. Uses the exact same
    protections as ``_check_tld_batches``: bounded concurrency, retries with
    backoff on transient throttles (429/5xx), auth-error abort (never multiply
    login failures), and binary-split poison isolation (a bad label/TLD pair is
    dropped, never the whole run). Returns the flat raw check results; callers
    group them by ``name`` per label.
    """
    if not labels or not tlds_to_check:
        return []

    import asyncio

    pairs: list[dict[str, str]] = [
        {"name": lab, "extension": tld} for lab in labels for tld in tlds_to_check
    ]
    BATCH = _DOMAIN_SEARCH_BATCH_SIZE
    CONCURRENCY = concurrency or _DOMAIN_SEARCH_CONCURRENCY
    MAX_RETRIES = max_retries or _DOMAIN_SEARCH_RETRIES
    headers = await _auth_headers()

    total_batches = max(1, (len(pairs) + BATCH - 1) // BATCH)
    logger.info(
        "[OPENPROVIDER_SEARCH] Random batch plan labels=%s tlds=%s pairs=%s "
        "batch_size=%s total_batches=%s concurrency=%s provider=%s",
        len(labels), len(tlds_to_check), len(pairs), BATCH, total_batches,
        CONCURRENCY, provider or "registry",
    )

    class _PoisonBatchError(RuntimeError):
        def __init__(self, message: str, *, chunk: list[dict[str, str]]) -> None:
            super().__init__(message)
            self.chunk = chunk

    async def _check_chunk(chunk: list[dict[str, str]], idx: int) -> list[dict[str, Any]]:
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                payload: dict[str, Any] = {"domains": chunk, "with_price": True}
                if provider:
                    payload["provider"] = provider
                resp = await client.post(
                    f"{_base_url()}/v1beta/domains/check",
                    headers=headers,
                    json=payload,
                )
                if _response_is_auth_error(resp):
                    logger.error(
                        "[OPENPROVIDER_SEARCH] domains/check authentication error "
                        "(HTTP %s). Not retrying.",
                        resp.status_code,
                    )
                    raise RuntimeError(
                        _format_http_error("domains/check", resp.status_code, resp.text or "")
                    )
                if resp.status_code >= 400:
                    is_poison = False
                    if resp.status_code == 500:
                        try:
                            body = resp.json()
                            if body.get("code") == 10005:
                                logger.error(
                                    "[OPENPROVIDER_SEARCH] domains/check access denied (code=10005). "
                                    "Not retrying — fix the API IP whitelist in cp.openprovider.eu "
                                    "and OPENPROVIDER_CLIENT_IP."
                                )
                                raise RuntimeError(
                                    _format_http_error("domains/check", resp.status_code, resp.text or "")
                                )
                            if body.get("code") in _DOMAIN_CHECK_POISON_CODES:
                                is_poison = True
                                desc = body.get("desc") or body.get("message") or "unknown"
                                logger.warning(
                                    "[OPENPROVIDER_SEARCH] HTTP 500 on pair-batch (size %s) "
                                    "with poison code %s - treating as poisoned",
                                    len(chunk), body.get("code"),
                                )
                                raise _PoisonBatchError(
                                    f"OpenProvider domains/check batch poisoned (code={body.get('code')}): {desc}",
                                    chunk=chunk,
                                )
                        except json.JSONDecodeError:
                            pass
                        except _PoisonBatchError:
                            raise

                    if resp.status_code in (429, 500, 502, 503, 504) and not is_poison:
                        logger.warning(
                            "[OPENPROVIDER_SEARCH] Pair-batch %s attempt %s got HTTP %s, retrying. Body: %s",
                            idx + 1, attempt, resp.status_code, (resp.text or "")[:200],
                        )
                        last_err = RuntimeError(
                            _format_http_error("domains/check", resp.status_code, resp.text or "")
                        )
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    logger.error(
                        "[OPENPROVIDER_SEARCH] Bulk check failed HTTP %s: %s",
                        resp.status_code,
                        (resp.text or "")[:800],
                    )
                    raise RuntimeError(
                        _format_http_error("domains/check", resp.status_code, resp.text or "")
                    )

                try:
                    body = resp.json()
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Registrar domains/check returned invalid JSON.") from exc
                if body.get("code") != 0:
                    code = body.get("code")
                    desc = body.get("desc") or body.get("message") or "unknown"
                    if code in _DOMAIN_CHECK_POISON_CODES:
                        raise _PoisonBatchError(
                            f"OpenProvider domains/check batch poisoned (code={code}): {desc}",
                            chunk=chunk,
                        )
                    raise RuntimeError(f"Registrar domains/check error: {desc}")
                return body.get("data", {}).get("results", [])
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = exc
                logger.warning(
                    "[OPENPROVIDER_SEARCH] Pair-batch %s attempt %s transport error, retrying: %s",
                    idx + 1, attempt, exc,
                )
                await asyncio.sleep(min(2 ** attempt, 8))
        raise RuntimeError(
            f"OpenProvider domains/check failed after {MAX_RETRIES} attempts for pair-batch {idx + 1}."
        ) from last_err

    async def _check_isolated(chunk: list[dict[str, str]], idx: int) -> list[dict[str, Any]]:
        """Isolate poison pairs via binary split so one bad label/TLD cannot
        sink its siblings. The bad pair is dropped silently."""
        try:
            return await _check_chunk(chunk, idx)
        except _PoisonBatchError as exc:
            bad_chunk = exc.chunk
            if len(bad_chunk) <= 1:
                logger.warning(
                    "[OPENPROVIDER_SEARCH] Dropping unpriceable label/TLD pair %s",
                    bad_chunk[0],
                )
                return []
            mid = len(bad_chunk) // 2
            left, right = await asyncio.gather(
                _check_isolated(bad_chunk[:mid], idx),
                _check_isolated(bad_chunk[mid:], idx),
            )
            return left + right

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _bounded(chunk: list[dict[str, str]], idx: int) -> list[dict[str, Any]]:
        async with semaphore:
            return await _check_isolated(chunk, idx)

    chunks = [pairs[i : i + BATCH] for i in range(0, len(pairs), BATCH)]

    limits = httpx.Limits(
        max_connections=max(CONCURRENCY * 2, 10),
        max_keepalive_connections=max(CONCURRENCY * 2, 10),
    )
    async with _op_http_client(timeout=90.0, limits=limits) as client:
        tasks = [_bounded(chunk, i) for i, chunk in enumerate(chunks)]
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
        raw_results: list[dict[str, Any]] = []
        failed_chunks = 0
        for res in chunk_results:
            if isinstance(res, Exception):
                err_l = str(res).lower()
                if (
                    "http 401" in err_l
                    or "code=196" in err_l
                    or "circuit breaker" in err_l
                    or (
                        "authentication" in err_l
                        and ("failed" in err_l or "error" in err_l or "login" in err_l)
                    )
                ):
                    logger.error(
                        "[OPENPROVIDER_SEARCH] Aborting random search on authentication failure: %s",
                        res,
                    )
                    raise res
                failed_chunks += 1
                logger.error(
                    "[OPENPROVIDER_SEARCH] Random pair-batch failed permanently: %s", res,
                )
                continue
            raw_results.extend(res)

    if not raw_results and failed_chunks:
        raise RuntimeError(
            f"OpenProvider domains/check failed for all {failed_chunks} pair-batch(es)."
        )

    logger.info(
        "[OPENPROVIDER_SEARCH] Random batch check returned %s results for %s labels",
        len(raw_results),
        len(labels),
    )
    return raw_results


# Number of curated priority TLDs checked on the fast first page (page 1). The
# remaining priority TLDs (beyond this count) are checked FIRST during the
# "Load more" remaining scan, so no curated TLD is ever skipped or duplicated
# between page 1 and the remaining pages.
_FIRST_PAGE_PRIORITY_COUNT = 60


def _sanitize_search_label(label: str) -> str:
    from app.utils.domain_label import sanitize_sld

    return sanitize_sld(label)


def _priority_tlds_deduped() -> list[str]:
    """Curated priority TLDs, de-duplicated with original order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _PRIORITY_TLDS:
        tld = raw.lstrip(".")
        if tld and tld not in seen:
            seen.add(tld)
            out.append(tld)
    return out


async def search_domains_label_first_page(
    label: str,
    max_tlds: int = _FIRST_PAGE_PRIORITY_COUNT,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    Fast first-page availability search using only the curated priority TLDs.

    This keeps the *initial* search-tlds response fast (a handful of parallel
    batches) instead of scanning the entire 1000+ TLD catalog up front — which
    previously pushed the synchronous request past the gateway timeout. The full
    catalog is fetched lazily via ``search_domains_label_remaining``.

    Returns ``(results, more_available, continuation_token)`` where
    ``continuation_token`` is the last priority TLD checked, used to resume the
    remaining-catalog scan without re-checking priority TLDs.
    """
    label = _sanitize_search_label(label)
    if not label:
        return [], False, None

    # Priority TLDs first (cheap, fast, the ones users care about most).
    priority_deduped = _priority_tlds_deduped()[:max(1, max_tlds)]

    logger.info(
        "[OPENPROVIDER_SEARCH] First-page scan (priority only) for %s: %s TLDs",
        label, len(priority_deduped),
    )
    results = await _check_tld_batches(label, priority_deduped)
    token = priority_deduped[-1] if priority_deduped else None
    return results, True, token


async def search_domains_label_first_page_chunk(
    label: str,
    chunk_index: int = 0,
    chunk_size: int = 12,
    max_tlds: int = _FIRST_PAGE_PRIORITY_COUNT,
) -> tuple[list[dict[str, Any]], int, int, bool]:
    """
    Progressive first-page wave: check one slice of the curated priority TLDs.

    Used by the Homepage Domain Names loader so the UI can paint available cards
    as each wave finishes and drive a real 1→100% progress bar.
    Returns ``(results, chunk_index, chunk_total, more_chunks)``.
    """
    label = _sanitize_search_label(label)
    if not label:
        return [], 0, 1, False

    chunk_index = max(0, int(chunk_index))
    chunk_size = max(1, min(int(chunk_size), max(1, max_tlds)))
    priority_deduped = _priority_tlds_deduped()[: max(1, max_tlds)]
    chunk_total = max(1, (len(priority_deduped) + chunk_size - 1) // chunk_size)
    if chunk_index >= chunk_total:
        return [], chunk_index, chunk_total, False

    start = chunk_index * chunk_size
    window = priority_deduped[start : start + chunk_size]
    logger.info(
        "[OPENPROVIDER_SEARCH] First-page chunk %s/%s for %s: %s TLDs",
        chunk_index + 1,
        chunk_total,
        label,
        len(window),
    )
    results = await _check_tld_batches(label, window)
    more_chunks = chunk_index + 1 < chunk_total
    return results, chunk_index, chunk_total, more_chunks


async def search_domains_label_remaining(
    label: str,
    after_tld: str | None = None,
    max_tlds: int = 1000,
    chunk_size: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    Resume the full-catalog scan *after* the priority TLDs.

    Called by the incremental "Load more" storefront flow so the long tail of
    the TLD catalog is fetched in separate, non-blocking requests rather than
    blocking the first response.

    Two windowing modes are supported over the remaining (non-priority) catalog:

    * ``offset`` (preferred, stateless): scan ``remaining[offset:offset+chunk_size]``.
      This gives contiguous, reproducible pages for page-based "Load more"
      without any server-side cursor state.
    * ``after_tld`` (legacy continuation token): resume immediately after the
      given TLD. Retained for backward compatibility.

    Returns ``(results, more_available, continuation_token)``. ``more_available``
    is ``False`` when the whole catalog has been consumed.
    """
    label = _sanitize_search_label(label)
    if not label:
        return [], False, None

    all_tlds = await _resolve_tlds_to_check(label, max_tlds=max_tlds)
    if not all_tlds:
        return [], False, None

    # Skip TLDs already covered by the priority first-page scan.
    if after_tld:
        after = after_tld.lstrip(".")
        if after in all_tlds:
            idx = all_tlds.index(after)
            remaining = all_tlds[idx + 1:]
        else:
            # The token is not in the catalog (priority list differs from
            # catalog ordering) — fall back to skipping known priority TLDs.
            priority = {t.lstrip(".") for t in _PRIORITY_TLDS}
            remaining = [t for t in all_tlds if t not in priority]
    else:
        # Offset mode (page-based "Load more"). The remaining universe is:
        #   1. the curated priority TLDs NOT already checked on the first page
        #      (priority_all[_FIRST_PAGE_PRIORITY_COUNT:]) — checked first so no
        #      curated TLD is ever skipped, and
        #   2. the rest of the live catalog, excluding every priority TLD so
        #      there are no duplicates with page 1 or the priority tail.
        priority_all = _priority_tlds_deduped()
        priority_set = set(priority_all)
        first_page_covered = set(priority_all[:_FIRST_PAGE_PRIORITY_COUNT])
        priority_tail = [t for t in priority_all if t not in first_page_covered]
        catalog_extras = [t for t in all_tlds if t not in priority_set]
        remaining = priority_tail + catalog_extras

    logger.info(
        "[OPENPROVIDER_SEARCH] Remaining-catalog scan for %s: %s TLDs "
        "(after=%s, offset=%s, chunk_size=%s)",
        label, len(remaining), after_tld, offset, chunk_size,
    )
    if not remaining:
        return [], False, None

    start = max(0, int(offset))
    if start >= len(remaining):
        return [], False, None

    more_available = False
    if chunk_size:
        end = start + chunk_size
        more_available = end < len(remaining)
        window = remaining[start:end]
    else:
        window = remaining[start:]

    if not window:
        return [], more_available, None

    results = await _check_tld_batches(label, window)
    token = window[-1] if window else None
    return results, more_available, token


async def search_domains_label(label: str, max_tlds: int = 200) -> list[dict[str, Any]]:
    """
    Back-compat helper: scan the entire TLD set and return every result.

    Used only by tests / callers that need the full synchronous result. New code
    should use ``search_domains_label_first_page`` + ``search_domains_label_remaining``
    to stay within gateway timeouts.
    """
    tlds_to_check = await _resolve_tlds_to_check(label, max_tlds=max_tlds)
    return await _check_tld_batches(label, tlds_to_check)


def is_registration_confirmed(details: dict[str, Any]) -> bool:
    status = str(details.get("status") or details.get("currentstatus") or "").upper()
    return status in ("ACT", "ACTIVE", "OK", "COMPLETED")


def parse_raa_verification_status(details: dict[str, Any]) -> str:
    # Check verification email/email verification status
    for key in ("verification_email", "email_verification", "owner_email_verification"):
        ve = details.get(key)
        if isinstance(ve, dict):
            status = str(ve.get("status") or "").lower()
            if status == "verified":
                return "VERIFIED"
            if status in ("in progress", "pending"):
                return "PENDING"
            if status == "failed":
                return "SUSPENDED"
            if status == "not verified":
                return "PENDING"
    # Fallbacks:
    for key in ("verification_status", "email_verification_status", "raaVerificationStatus"):
        val = str(details.get(key) or "").lower()
        if val == "verified":
            return "VERIFIED"
        if val in ("in progress", "pending"):
            return "PENDING"
        if val == "failed":
            return "SUSPENDED"
    return "UNKNOWN"


def parse_expiry_from_details(details: dict[str, Any]) -> datetime | None:
    from datetime import datetime, timezone
    for key in ("expiration_date", "expirationDate", "expiry_date", "expiryDate", "endtime"):
        val = details.get(key)
        if val:
            try:
                if isinstance(val, (int, float)):
                    return datetime.fromtimestamp(val, tz=timezone.utc)
                text = str(val).strip()
                if text.isdigit():
                    return datetime.fromtimestamp(int(text), tz=timezone.utc)
                if " " in text:
                    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
                else:
                    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                pass
    return None


def order_details_current_status(details: dict[str, Any]) -> str:
    return str(details.get("status") or details.get("currentstatus") or "")


async def update_nameservers(domain_id: str, nameservers: list[str]) -> bool:
    logger.info("[OPENPROVIDER_REGISTRATION] Updating nameservers for domain ID %s: %s", domain_id, nameservers)
    headers = await _auth_headers()
    payload = {
        "name_servers": [{"name": ns.strip()} for ns in nameservers if ns.strip()]
    }
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.put(
            f"{_base_url()}/v1beta/domains/{domain_id}",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_REGISTRATION] Update nameservers failed: %s", resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        return True


async def renew_domain(domain_id: str, period_years: int = 1) -> bool:
    logger.info("[OPENPROVIDER_REGISTRATION] Renewing domain ID %s for %d years", domain_id, period_years)
    headers = await _auth_headers()
    payload = {
        "period": period_years
    }
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/domains/{domain_id}/renew",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_REGISTRATION] Renew domain failed: %s", resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        return True


async def transfer_domain(
    name: str,
    extension_no_dot: str,
    auth_code: str,
    handle: str,
    period_years: int = 1
) -> dict:
    logger.info("[OPENPROVIDER_REGISTRATION] Transferring domain %s.%s, handle: %s", name, extension_no_dot, handle)
    name_servers = [{"name": ns} for ns in default_nameservers()]
    payload = {
        "domain": {"name": name, "extension": extension_no_dot},
        "auth_code": auth_code.strip(),
        "owner_handle": handle,
        "admin_handle": handle,
        "tech_handle": handle,
        "billing_handle": handle,
        "period": period_years,
        "name_servers": name_servers
    }
    headers = await _auth_headers()
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/domains/transfer",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_REGISTRATION] Transfer failed: %s", resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        body = resp.json()
        if body.get("code") != 0:
            raise RuntimeError(friendly_error_from_body(str(body)))
        return body.get("data", {})


async def get_dns_records(domain_name: str) -> list[dict[str, Any]]:
    logger.info("[OPENPROVIDER_DNS] Fetching records for zone %s", domain_name)
    if not is_configured():
        return [
            {"id": "mock-dns-1", "type": "A", "name": "@", "value": "192.168.1.1", "ttl": 3600},
            {"id": "mock-dns-2", "type": "CNAME", "name": "www", "value": "drymortar.in", "ttl": 3600},
            {"id": "mock-dns-3", "type": "MX", "name": "@", "value": "mail.drymortar.in", "ttl": 3600, "priority": 10},
        ]
    try:
        headers = await _auth_headers()
        async with _op_http_client(timeout=30.0) as client:
            resp = await client.get(
                f"{_base_url()}/v1beta/dns/zones/{domain_name}/records",
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.error("[OPENPROVIDER_DNS] Fetch records HTTP %d: %s", resp.status_code, resp.text)
                raise RuntimeError(friendly_error_from_body(resp.text))
            body = resp.json()
            data = body.get("data", {})
            records = data.get("records") or data.get("results") or []
            import base64
            import json
            for r in records:
                if "id" not in r:
                    identity = {k: v for k, v in r.items() if k != "id"}
                    ident_str = json.dumps(identity, sort_keys=True)
                    r["id"] = base64.urlsafe_b64encode(ident_str.encode()).decode()
            return records
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[OPENPROVIDER_DNS] Error fetching records: %s", e)
        raise RuntimeError(f"Failed to fetch DNS records: {e}") from e


async def _get_zone_records_raw(domain_name: str, headers: dict) -> list[dict]:
    """Internal: fetch raw records list for post-mutation verification."""
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/dns/zones/{domain_name}/records",
            headers=headers,
            params={"limit": 500},
        )
        if resp.status_code >= 400:
            return []
        return resp.json().get("data", {}).get("results", [])


def _normalize_name(name: str, domain_name: str) -> str:
    """Return the relative host label. OpenProvider GET returns FQDN; add/remove accepts both."""
    suffix = f".{domain_name}"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    if name == domain_name:
        return ""
    return name


def _records_match(a: dict, b: dict, domain_name: str) -> bool:
    """True if two records represent the same DNS entry (type + relative name + value)."""
    return (
        a.get("type", "").upper() == b.get("type", "").upper()
        and _normalize_name(a.get("name", ""), domain_name) == _normalize_name(b.get("name", ""), domain_name)
        and str(a.get("value", "")).strip() == str(b.get("value", "")).strip()
    )


async def create_dns_record(domain_name: str, payload: dict[str, Any]) -> bool:
    logger.info("[OPENPROVIDER_DNS] Creating record for zone %s: %s", domain_name, payload)
    if not is_configured():
        return True

    if "id" in payload:
        payload = payload.copy()
        payload.pop("id")

    zone = await get_dns_zone(domain_name)
    zone_id = zone.get("id") if zone else None

    put_payload = {
        "name": domain_name,
        "records": {
            "add": [payload]
        }
    }
    if zone_id:
        put_payload["id"] = zone_id

    headers = await _auth_headers()

    if "records" in payload and isinstance(payload["records"], dict):
        op_payload = payload
    else:
        record = dict(payload)
        name = str(record.get("name", "")).strip()
        if name == "@" or not name:
            record["name"] = domain_name
        else:
            record["name"] = name

        if "ttl" in record:
            try:
                record["ttl"] = int(record["ttl"])
            except (ValueError, TypeError):
                record["ttl"] = 3600
        else:
            record["ttl"] = 3600

        op_payload = {
            "records": {
                "add": [record]
            }
        }

    async with _op_http_client(timeout=30.0) as client:
        resp = await client.put(
            f"{_base_url()}/v1beta/dns/zones/{domain_name}",
            headers=headers,
            json=put_payload,
        )
        resp_body = resp.json() if resp.content else {}
        logger.info("[OPENPROVIDER_DNS] Create PUT response %d: %s", resp.status_code, resp_body)
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_DNS] Create record failed HTTP %d: %s", resp.status_code, resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))

    # Post-mutation verification: confirm record now exists in zone
    headers2 = await _auth_headers()
    live_records = await _get_zone_records_raw(domain_name, headers2)
    added = any(_records_match(r, payload, domain_name) for r in live_records)
    if not added:
        logger.error(
            "[OPENPROVIDER_DNS] Create appeared to succeed (HTTP 200) but record not found in zone GET: %s",
            payload,
        )
        raise RuntimeError("DNS record could not be verified after adding. Please try again.")
    logger.info("[OPENPROVIDER_DNS] Create verified — record confirmed in live zone.")
    return True


async def delete_dns_record(domain_name: str, record_id: str) -> bool:
    logger.info("[OPENPROVIDER_DNS] Deleting record %s in zone %s", record_id, domain_name)
    if not is_configured():
        return True

    import base64
    import json as _json
    try:
        ident_str = base64.urlsafe_b64decode(record_id.encode()).decode()
        target_record = _json.loads(ident_str)
    except Exception as exc:
        logger.error("[OPENPROVIDER_DNS] Invalid record ID format: %s", exc)
        raise RuntimeError("Invalid record ID. Please try again.") from exc

    zone = await get_dns_zone(domain_name)
    zone_id = zone.get("id") if zone else None

    # Clean record for OpenProvider API (remove read-only fields, normalise name)
    valid_keys = {"type", "name", "value", "ttl", "prio"}
    clean_target = {k: v for k, v in target_record.items() if k in valid_keys}
    clean_target["name"] = _normalize_name(clean_target.get("name", ""), domain_name)

    # Pre-check: confirm the record actually exists in the live zone before attempting remove.
    headers = await _auth_headers()
    live_records = await _get_zone_records_raw(domain_name, headers)
    exists = any(_records_match(r, clean_target, domain_name) for r in live_records)
    if not exists:
        logger.warning(
            "[OPENPROVIDER_DNS] Delete pre-check: record not found in live zone, aborting. target=%s",
            clean_target,
        )
        raise RuntimeError("DNS record not found. It may have already been deleted. Please refresh and try again.")

    put_payload = {
        "name": domain_name,
        "records": {
            "remove": [clean_target]
        }
    }
    if zone_id:
        put_payload["id"] = zone_id

    async with _op_http_client(timeout=30.0) as client:
        resp = await client.put(
            f"{_base_url()}/v1beta/dns/zones/{domain_name}",
            headers=headers,
            json=put_payload,
        )
        resp_body = resp.json() if resp.content else {}
        logger.info("[OPENPROVIDER_DNS] Delete PUT response %d: %s", resp.status_code, resp_body)
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_DNS] Delete record failed HTTP %d: %s", resp.status_code, resp.text)
            raise RuntimeError("DNS service is currently unavailable. Please try again later.")

    # Post-mutation verification: confirm record is gone
    headers2 = await _auth_headers()
    live_after = await _get_zone_records_raw(domain_name, headers2)
    still_exists = any(_records_match(r, clean_target, domain_name) for r in live_after)
    if still_exists:
        logger.error(
            "[OPENPROVIDER_DNS] Delete appeared to succeed (HTTP 200) but record still present in zone GET: %s",
            clean_target,
        )
        raise RuntimeError("DNS record could not be removed. Please try again.")
    logger.info("[OPENPROVIDER_DNS] Delete verified — record confirmed removed from live zone.")
    return True

async def update_dns_record(domain_name: str, old_record_id: str, new_payload: dict[str, Any]) -> bool:
    logger.info("[OPENPROVIDER_DNS] Updating record %s in zone %s", old_record_id, domain_name)
    if not is_configured():
        return True

    import base64
    import json as _json
    try:
        ident_str = base64.urlsafe_b64decode(old_record_id.encode()).decode()
        target_record = _json.loads(ident_str)
    except Exception as exc:
        logger.error("[OPENPROVIDER_DNS] Invalid record ID format: %s", exc)
        raise RuntimeError("Invalid record ID. Please try again.") from exc

    if "id" in new_payload:
        new_payload = new_payload.copy()
        new_payload.pop("id")

    zone = await get_dns_zone(domain_name)
    zone_id = zone.get("id") if zone else None

    # Clean old record: keep only mutable fields, normalise name to relative host
    valid_keys = {"type", "name", "value", "ttl", "prio"}
    clean_target = {k: v for k, v in target_record.items() if k in valid_keys}
    clean_target["name"] = _normalize_name(clean_target.get("name", ""), domain_name)

    # Normalise new payload name to relative host as well
    new_payload["name"] = _normalize_name(new_payload.get("name", ""), domain_name)

    # Pre-check: confirm the old record actually exists in the live zone
    headers = await _auth_headers()
    live_records = await _get_zone_records_raw(domain_name, headers)
    exists = any(_records_match(r, clean_target, domain_name) for r in live_records)
    if not exists:
        logger.warning(
            "[OPENPROVIDER_DNS] Update pre-check: original record not found in live zone. target=%s",
            clean_target,
        )
        raise RuntimeError("DNS record not found. It may have already been modified or deleted. Please refresh and try again.")

    add_payload = {
        "name": domain_name,
        "records": {
            "add": [new_payload]
        }
    }
    if zone_id:
        add_payload["id"] = zone_id

    remove_payload = {
        "name": domain_name,
        "records": {
            "remove": [clean_target]
        }
    }
    if zone_id:
        remove_payload["id"] = zone_id

    async with _op_http_client(timeout=30.0) as client:
        # Step 1: Add new record (ensures zero downtime)
        resp1 = await client.put(
            f"{_base_url()}/v1beta/dns/zones/{domain_name}",
            headers=headers,
            json=add_payload,
        )
        resp1_body = resp1.json() if resp1.content else {}
        logger.info("[OPENPROVIDER_DNS] Update(Add) PUT response %d: %s", resp1.status_code, resp1_body)
        if resp1.status_code >= 400:
            logger.error("[OPENPROVIDER_DNS] Update(Add) record failed HTTP %d: %s", resp1.status_code, resp1.text)
            raise RuntimeError("Unable to update DNS record. Please try again.")

        # Step 2: Remove old record
        resp2 = await client.put(
            f"{_base_url()}/v1beta/dns/zones/{domain_name}",
            headers=headers,
            json=remove_payload,
        )
        resp2_body = resp2.json() if resp2.content else {}
        logger.info("[OPENPROVIDER_DNS] Update(Remove) PUT response %d: %s", resp2.status_code, resp2_body)
        if resp2.status_code >= 400:
            logger.error("[OPENPROVIDER_DNS] Update(Remove) record failed HTTP %d: %s", resp2.status_code, resp2.text)
            raise RuntimeError("DNS record updated partially (old record remains). Please clean up manually.")

    # Post-mutation verification: confirm old record is gone and new record is present
    headers2 = await _auth_headers()
    live_after = await _get_zone_records_raw(domain_name, headers2)
    old_still_present = any(_records_match(r, clean_target, domain_name) for r in live_after)
    new_present = any(_records_match(r, new_payload, domain_name) for r in live_after)
    if old_still_present or not new_present:
        logger.error(
            "[OPENPROVIDER_DNS] Update appeared to succeed (HTTP 200) but zone state did not change as expected. "
            "old_still_present=%s new_present=%s target=%s new=%s",
            old_still_present, new_present, clean_target, new_payload,
        )
        raise RuntimeError("DNS record could not be updated. Please refresh and try again.")
    logger.info("[OPENPROVIDER_DNS] Update verified — old record gone, new record confirmed in live zone.")
    return True


async def get_dns_zone(domain_name: str) -> dict | None:
    """GET /v1beta/dns/zones/{domain_name} — returns zone dict or None if missing."""
    logger.info("[OPENPROVIDER_DNS] Checking zone existence for %s", domain_name)
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/dns/zones/{domain_name}",
            headers=headers,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            body_text = (resp.text or "").lower()
            if "zone specified is not found" in body_text:
                logger.info("[OPENPROVIDER_DNS] Zone %s not found (HTTP %d), treating as absent", domain_name, resp.status_code)
                return None
            logger.error("[OPENPROVIDER_DNS] Get zone HTTP %d: %s", resp.status_code, resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        body = resp.json()
        return body.get("data") or {}


async def create_dns_zone(domain_name: str) -> dict:
    """POST /v1beta/dns/zones — create a MASTER DNS zone.

    Idempotent: if OpenProvider returns an 'already exists' error, fetch and
    return the existing zone instead of failing.
    """
    logger.info("[OPENPROVIDER_DNS] Creating MASTER zone for %s", domain_name)
    headers = await _auth_headers()
    # OpenProvider expects {"domain": {"name": "example", "extension": "com"}}
    dot_pos = domain_name.find(".")
    if dot_pos > 0:
        sld = domain_name[:dot_pos]
        ext = domain_name[dot_pos + 1:]
    else:
        sld = domain_name
        ext = ""
    payload: dict[str, Any] = {
        "domain": {"name": sld, "extension": ext},
        "type": "master",
    }
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/dns/zones",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            text = resp.text or ""
            lower = text.lower()
            if "already exists" in lower or resp.status_code == 409:
                logger.info("[OPENPROVIDER_DNS] Zone %s already exists, fetching it", domain_name)
                existing = await get_dns_zone(domain_name)
                if existing is not None:
                    return existing
            logger.error("[OPENPROVIDER_DNS] Create zone HTTP %d: %s", resp.status_code, text)
            raise RuntimeError(friendly_error_from_body(text))
        body = resp.json()
    data = body.get("data") or {}
    logger.info("[OPENPROVIDER_DNS] Zone created for %s: %s", domain_name, data)
    return data


async def get_auth_code(domain_id: str, *, auth_code_type: str = "external") -> str:
    """Official ``GET /v1beta/domains/{id}/authcode``."""
    headers = await _auth_headers()
    params = {"auth_code_type": auth_code_type or "external"}
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/domains/{domain_id}/authcode",
            headers=headers,
            params=params,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("domains/authcode", resp.status_code, resp.text or "")
            )
        body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(friendly_error_from_body(str(body)))
    data = body.get("data") or {}
    auth = data.get("auth_code") or data.get("authCode")
    if isinstance(auth, dict):
        auth = (
            auth.get("auth_code")
            or auth.get("code")
            or auth.get("authCode")
            or auth.get("pw")
        )
    code = str(auth or "").strip()
    if not code:
        raise RuntimeError("Registrar returned an empty auth code.")
    return code


async def reset_auth_code(domain_id: str, *, auth_code_type: str = "external") -> str:
    """Official ``POST /v1beta/domains/{id}/authcode/reset``."""
    headers = await _auth_headers()
    payload = {"auth_code_type": auth_code_type or "external"}
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/domains/{domain_id}/authcode/reset",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("domains/authcode/reset", resp.status_code, resp.text or "")
            )
        body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(friendly_error_from_body(str(body)))
    data = body.get("data") or {}
    info = data.get("auth_code") or data.get("authCode") or data
    if isinstance(info, dict):
        code = (
            info.get("auth_code")
            or info.get("code")
            or info.get("authCode")
            or info.get("pw")
        )
    else:
        code = info
    result = str(code or "").strip()
    if not result:
        # Some TLDs only trigger delivery; fall back to get
        return await get_auth_code(domain_id, auth_code_type=auth_code_type)
    return result


async def set_domain_locked(domain_id: str, locked: bool) -> bool:
    """Official domain update: set ``is_locked``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.put(
            f"{_base_url()}/v1beta/domains/{domain_id}",
            headers=headers,
            json={"is_locked": bool(locked)},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("domains/lock", resp.status_code, resp.text or "")
            )
        body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(friendly_error_from_body(str(body)))
    return True


async def update_dnssec(
    domain_id: str,
    enabled: bool,
    *,
    dnssec_keys: list[dict[str, Any]] | None = None,
    domain_fqdn: str | None = None,
) -> bool:
    """
    Enable/disable DNSSEC via official ``PUT /v1beta/domains/{id}``.

    Per OpenProvider docs (reseller DNSSEC guide + REST Update Domain):
    - On OpenProvider nameservers: set ``is_dnssec_enabled`` only — OP signs
      the zone and publishes DS/keys at the registry. Never send fake/mock keys.
    - On custom nameservers: also pass real ``dnssec_keys``
      (flags / alg|algorithm / protocol / pubKey|public_key).

    ``domain_fqdn`` is accepted for call-site clarity / future zone sync; domain-level
    ``is_dnssec_enabled`` is the authoritative registrar toggle.
    """
    _ = domain_fqdn  # reserved for logging / future zone alignment
    logger.info(
        "[OPENPROVIDER_DNSSEC] Setting is_dnssec_enabled=%s domain_id=%s has_keys=%s",
        enabled,
        domain_id,
        bool(dnssec_keys),
    )
    if not is_configured():
        return True

    payload: dict[str, Any] = {"is_dnssec_enabled": bool(enabled)}
    if dnssec_keys:
        # Normalize legacy key field names to OP API Format DNSSEC Keys.
        normalized: list[dict[str, Any]] = []
        for raw in dnssec_keys:
            if not isinstance(raw, dict):
                continue
            key = {
                "flags": raw.get("flags"),
                "protocol": raw.get("protocol", 3),
                "alg": raw.get("alg") or raw.get("algorithm"),
                "pubKey": raw.get("pubKey") or raw.get("public_key") or raw.get("pubkey"),
            }
            if key["flags"] is None or key["alg"] is None or not key["pubKey"]:
                raise RuntimeError(
                    "Invalid DNSSEC key: flags, alg, and pubKey are required."
                )
            normalized.append(key)
        payload["dnssec_keys"] = normalized

    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.put(
            f"{_base_url()}/v1beta/domains/{domain_id}",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("[OPENPROVIDER_DNSSEC] Domain DNSSEC update failed: %s", resp.text)
            raise RuntimeError(friendly_error_from_body(resp.text))
        body = resp.json()
        if body.get("code") != 0:
            raise RuntimeError(friendly_error_from_body(str(body)))
    return True


# ─── SSL Certificates (public REST: /v1beta/ssl/*) ───────────────────────────


def _ssl_api_data(body: dict[str, Any], *, operation: str) -> Any:
    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"OpenProvider {operation} error: {desc}")
    return body.get("data")


async def list_ssl_products(
    *,
    with_price: bool = True,
    with_description: bool = False,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Official ``GET /v1beta/ssl/products``."""
    headers = await _auth_headers()
    params: dict[str, Any] = {
        "limit": max(1, min(int(limit), 1000)),
        "offset": max(0, int(offset)),
        "with_price": bool(with_price),
    }
    if with_description:
        params["with_description"] = True
    async with _op_http_client(timeout=45.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/ssl/products",
            headers=headers,
            params=params,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("ssl/products", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _ssl_api_data(body, operation="ssl/products")
    if not isinstance(data, dict):
        return []
    results = data.get("results") or []
    return [r for r in results if isinstance(r, dict)]


async def get_ssl_product(product_id: int) -> dict[str, Any]:
    """Official ``GET /v1beta/ssl/products/{id}`` (metadata; prefer list for prices)."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/ssl/products/{int(product_id)}",
            headers=headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    f"ssl/products/{product_id}", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    data = _ssl_api_data(body, operation=f"ssl/products/{product_id}")
    return data if isinstance(data, dict) else {}


async def list_ssl_approver_emails(product_id: int, domain: str) -> list[str]:
    """Official ``GET /v1beta/ssl/approver-emails``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/ssl/approver-emails",
            headers=headers,
            params={"product_id": int(product_id), "domain": domain.strip().lower()},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("ssl/approver-emails", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _ssl_api_data(body, operation="ssl/approver-emails")
    if not isinstance(data, dict):
        return []
    results = data.get("results") or []
    return [str(e).strip() for e in results if str(e).strip()]


async def generate_ssl_csr(
    *,
    common_name: str,
    country: str,
    email: str,
    organization: str,
    locality: str,
    state: str,
    unit: str = "IT",
    bits: int = 2048,
    subject_alternative_name: list[str] | None = None,
    with_config: bool = False,
    signature_hash_algorithm: str = "sha2",
) -> dict[str, str]:
    """Official ``POST /v1beta/ssl/csr``. Returns ``csr`` and private ``key``."""
    payload: dict[str, Any] = {
        "bits": int(bits),
        "common_name": common_name.strip().lower(),
        "country": (country or "IN").strip().upper()[:2],
        "email": email.strip(),
        "organization": (organization or "Private").strip(),
        "locality": (locality or "N/A").strip(),
        "state": (state or "N/A").strip(),
        "unit": (unit or "IT").strip(),
        "with_config": bool(with_config),
        "signature_hash_algorithm": signature_hash_algorithm or "sha2",
    }
    if subject_alternative_name:
        payload["subject_alternative_name"] = [
            s.strip().lower() for s in subject_alternative_name if s and s.strip()
        ]
    headers = await _auth_headers()
    async with _op_http_client(timeout=45.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/ssl/csr",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("ssl/csr", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _ssl_api_data(body, operation="ssl/csr")
    if not isinstance(data, dict):
        raise RuntimeError("OpenProvider ssl/csr returned empty data")
    csr = str(data.get("csr") or "").strip()
    key = str(data.get("key") or "").strip()
    if not csr or not key:
        raise RuntimeError("OpenProvider ssl/csr did not return csr and key")
    return {"csr": csr, "key": key}


async def create_ssl_order(payload: dict[str, Any]) -> int:
    """Official ``POST /v1beta/ssl/orders``. Returns new order id."""
    headers = await _auth_headers()
    body_payload = dict(payload)
    # OpenAPI default for start_provision is false — always set explicitly when provisioning.
    if "start_provision" not in body_payload:
        body_payload["start_provision"] = True
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/ssl/orders",
            headers=headers,
            json=body_payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("ssl/orders", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _ssl_api_data(body, operation="ssl/orders")
    if not isinstance(data, dict) or data.get("id") is None:
        raise RuntimeError("OpenProvider ssl/orders did not return an id")
    return int(data["id"])


async def get_ssl_order(order_id: int) -> dict[str, Any]:
    """Official ``GET /v1beta/ssl/orders/{id}``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/ssl/orders/{int(order_id)}",
            headers=headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    f"ssl/orders/{order_id}", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    data = _ssl_api_data(body, operation=f"ssl/orders/{order_id}")
    return data if isinstance(data, dict) else {}


async def resend_ssl_approver_email(order_id: int) -> bool:
    """Official ``POST /v1beta/ssl/orders/{id}/approver-email/resend``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/ssl/orders/{int(order_id)}/approver-email/resend",
            headers=headers,
            json={},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    f"ssl/orders/{order_id}/approver-email/resend",
                    resp.status_code,
                    resp.text or "",
                )
            )
        body = resp.json()
    _ssl_api_data(body, operation="ssl/approver-email/resend")
    return True


def extract_ssl_period_price(
    product: dict[str, Any],
    period: int = 1,
) -> tuple[float, str]:
    """Return (amount, currency) for a product period from ``prices[]``."""
    years = max(1, int(period or 1))
    for entry in product.get("prices") or []:
        if not isinstance(entry, dict):
            continue
        if int(entry.get("period") or 0) != years:
            continue
        price_group = entry.get("price") if isinstance(entry.get("price"), dict) else {}
        reseller = price_group.get("reseller") if isinstance(price_group.get("reseller"), dict) else {}
        product_p = price_group.get("product") if isinstance(price_group.get("product"), dict) else {}
        if reseller.get("price") is not None:
            return float(reseller["price"]), str(reseller.get("currency") or "EUR").upper()
        if product_p.get("price") is not None:
            return float(product_p["price"]), str(product_p.get("currency") or "EUR").upper()
    raise RuntimeError(
        f"No SSL price found for product_id={product.get('id')} period={years}"
    )


# ─── Mailcow / Professional Email (public REST: /v1beta/mailcow/*) ───────────


def _mailcow_api_data(body: dict[str, Any], *, operation: str) -> Any:
    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"OpenProvider {operation} error: {desc}")
    return body.get("data")


def _mailcow_domain_payload(name: str, extension_no_dot: str) -> dict[str, str]:
    return {
        "name": (name or "").strip().lower(),
        "extension": (extension_no_dot or "").strip().lower().lstrip("."),
    }


async def mailcow_create_order(*, period_months: int = 1, quantity: int = 1) -> dict[str, Any]:
    """Official ``POST /v1beta/mailcow/orders`` — purchase mailbox seats."""
    headers = await _auth_headers()
    payload = {
        "period": str(max(1, int(period_months or 1))),
        "quantity": str(max(1, int(quantity or 1))),
    }
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/mailcow/orders",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("mailcow/orders", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation="mailcow/orders")
    return data if isinstance(data, dict) else {"success": bool(data)}


async def mailcow_list_domains(*, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Official ``GET /v1beta/mailcow/domains/list``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/mailcow/domains/list",
            headers=headers,
            params={"limit": max(1, min(int(limit), 500)), "offset": max(0, int(offset))},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("mailcow/domains/list", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation="mailcow/domains/list")
    if not isinstance(data, dict):
        return []
    results = data.get("results") or []
    return [r for r in results if isinstance(r, dict)]


async def mailcow_add_domain(
    *,
    name: str,
    extension_no_dot: str,
    owner_handle: str,
    description: str = "",
) -> dict[str, Any]:
    """Official ``POST /v1beta/mailcow/domains``."""
    headers = await _auth_headers()
    payload: dict[str, Any] = {
        "domain": _mailcow_domain_payload(name, extension_no_dot),
        "owner_handle": (owner_handle or "").strip(),
    }
    if description:
        payload["description"] = description.strip()
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/mailcow/domains",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("mailcow/domains", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation="mailcow/domains")
    return data if isinstance(data, dict) else {}


async def mailcow_assign_mailbox(
    *,
    name: str,
    extension_no_dot: str,
    mailbox: str,
    password: str,
    full_name: str = "",
    subscription_period_months: int = 1,
    reset_password: bool = False,
) -> dict[str, Any]:
    """Official ``POST /v1beta/mailcow/orders/assign``."""
    headers = await _auth_headers()
    payload: dict[str, Any] = {
        "domain": _mailcow_domain_payload(name, extension_no_dot),
        "mailbox": (mailbox or "").strip().lower(),
        "password": password,
        "reset_password": bool(reset_password),
        "subscription_period": str(max(1, int(subscription_period_months or 1))),
    }
    if full_name:
        payload["name"] = full_name.strip()
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/mailcow/orders/assign",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    "mailcow/orders/assign", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation="mailcow/orders/assign")
    return data if isinstance(data, dict) else {}


async def mailcow_edit_mailbox(
    *,
    name: str,
    extension_no_dot: str,
    mailbox: str,
    password: str | None = None,
    password_confirmation: str | None = None,
    full_name: str | None = None,
    reset_password: bool = False,
) -> bool:
    """Official ``POST /v1beta/mailcow/mailbox/edit``."""
    headers = await _auth_headers()
    payload: dict[str, Any] = {
        "domain": _mailcow_domain_payload(name, extension_no_dot),
        "mailbox": (mailbox or "").strip().lower(),
        "reset_password": bool(reset_password),
    }
    if password is not None:
        payload["password"] = password
        payload["password_confirmation"] = (
            password_confirmation if password_confirmation is not None else password
        )
    if full_name is not None:
        payload["name"] = full_name.strip()
    async with _op_http_client(timeout=45.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/mailcow/mailbox/edit",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("mailcow/mailbox/edit", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation="mailcow/mailbox/edit")
    if isinstance(data, dict):
        return bool(data.get("success", True))
    return True


async def mailcow_increase_mailbox_quota(
    *,
    name: str,
    extension_no_dot: str,
    mailbox: str,
    quota_gb: int,
) -> bool:
    """Official ``POST /v1beta/mailcow/mailbox/quota/increase``."""
    headers = await _auth_headers()
    payload = {
        "domain": _mailcow_domain_payload(name, extension_no_dot),
        "mailbox": (mailbox or "").strip().lower(),
        "quota": max(1, int(quota_gb or 1)),
    }
    async with _op_http_client(timeout=45.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/mailcow/mailbox/quota/increase",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    "mailcow/mailbox/quota/increase", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation="mailcow/mailbox/quota/increase")
    if isinstance(data, dict):
        return bool(data.get("success", True))
    return True


async def mailcow_get_mailbox_password(order_id: int) -> str:
    """Official ``GET /v1beta/mailcow/orders/{id}/password``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/mailcow/orders/{int(order_id)}/password",
            headers=headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    f"mailcow/orders/{order_id}/password",
                    resp.status_code,
                    resp.text or "",
                )
            )
        body = resp.json()
    data = _mailcow_api_data(body, operation=f"mailcow/orders/{order_id}/password")
    if not isinstance(data, dict):
        return ""
    return str(data.get("password") or "")


# ─── Domain Restore ───────────────────────────────────────────────────────────


async def restore_domain(
    domain_id: int | str,
    *,
    name: str,
    extension_no_dot: str,
) -> dict[str, Any]:
    """Official ``POST /v1beta/domains/{id}/restore``."""
    headers = await _auth_headers()
    payload = {
        "id": int(domain_id),
        "domain": {
            "name": (name or "").strip().lower(),
            "extension": (extension_no_dot or "").strip().lower().lstrip("."),
        },
    }
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/domains/{int(domain_id)}/restore",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    f"domains/{domain_id}/restore", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"OpenProvider domain restore error: {desc}")
    data = body.get("data")
    return data if isinstance(data, dict) else {"status": data}


# ─── EasyDMARC ────────────────────────────────────────────────────────────────


def _easydmarc_api_data(body: dict[str, Any], *, operation: str) -> Any:
    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"OpenProvider {operation} error: {desc}")
    return body.get("data")


async def easydmarc_create(*, name: str, extension_no_dot: str, owner_handle: str) -> dict[str, Any]:
    """Official ``POST /v1beta/easydmarcs``."""
    headers = await _auth_headers()
    payload = {
        "domain": {
            "name": (name or "").strip().lower(),
            "extension": (extension_no_dot or "").strip().lower().lstrip("."),
        },
        "owner_handle": (owner_handle or "").strip(),
    }
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/easydmarcs",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("easydmarcs", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _easydmarc_api_data(body, operation="easydmarcs")
    return data if isinstance(data, dict) else {}


async def easydmarc_get(order_id: int) -> dict[str, Any]:
    """Official ``GET /v1beta/easydmarcs`` with id filter via path list get by id if available.
    Swagger: GET /v1beta/easydmarcs is Get easy dmarc — use list + filter, or get via list.
    Prefer GET /v1beta/easydmarcs/list and filter; also try dedicated get if swagger Get uses query.
    """
    # Swagger has GET /v1beta/easydmarcs as Get and GET /v1beta/easydmarcs/list as List.
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/easydmarcs",
            headers=headers,
            params={"id": int(order_id)},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(f"easydmarcs/{order_id}", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _easydmarc_api_data(body, operation=f"easydmarcs/{order_id}")
    return data if isinstance(data, dict) else {}


async def easydmarc_sso_url(order_id: int) -> str:
    """Official ``GET /v1beta/easydmarcs/{id}/sso``."""
    headers = await _auth_headers()
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.get(
            f"{_base_url()}/v1beta/easydmarcs/{int(order_id)}/sso",
            headers=headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    f"easydmarcs/{order_id}/sso", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    data = _easydmarc_api_data(body, operation=f"easydmarcs/{order_id}/sso")
    if isinstance(data, dict):
        return str(data.get("url") or "")
    return ""


# ─── SpamExperts ──────────────────────────────────────────────────────────────


def _spam_api_data(body: dict[str, Any], *, operation: str) -> Any:
    if body.get("code") != 0:
        desc = body.get("desc") or body.get("message") or "unknown"
        raise RuntimeError(f"OpenProvider {operation} error: {desc}")
    return body.get("data")


async def spam_expert_create_domain(
    *,
    domain_name: str,
    destinations: list[dict[str, Any]] | None = None,
    products: dict[str, bool] | None = None,
    bundle: bool = False,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """Official ``POST /v1beta/spam-expert/domains``."""
    headers = await _auth_headers()
    payload: dict[str, Any] = {
        "domain_name": (domain_name or "").strip().lower(),
        "bundle": bool(bundle),
        "destinations": destinations
        or [{"hostname": f"mail.{(domain_name or '').strip().lower()}", "port": 25}],
        "products": products
        or {"incoming": True, "outgoing": False, "archiving": False},
    }
    if aliases:
        payload["aliases"] = [a.strip().lower() for a in aliases if a and a.strip()]
    async with _op_http_client(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/spam-expert/domains",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error("spam-expert/domains", resp.status_code, resp.text or "")
            )
        body = resp.json()
    data = _spam_api_data(body, operation="spam-expert/domains")
    return data if isinstance(data, dict) else {}


async def spam_expert_generate_login_url(
    *,
    domain_or_email: str,
    bundle: bool = False,
) -> str:
    """Official ``POST /v1beta/spam-expert/generate-login-url``."""
    headers = await _auth_headers()
    payload = {
        "domain_or_email": (domain_or_email or "").strip().lower(),
        "bundle": bool(bundle),
    }
    async with _op_http_client(timeout=30.0) as client:
        resp = await client.post(
            f"{_base_url()}/v1beta/spam-expert/generate-login-url",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                _format_http_error(
                    "spam-expert/generate-login-url", resp.status_code, resp.text or ""
                )
            )
        body = resp.json()
    data = _spam_api_data(body, operation="spam-expert/generate-login-url")
    if isinstance(data, dict):
        return str(data.get("url") or "")
    return ""

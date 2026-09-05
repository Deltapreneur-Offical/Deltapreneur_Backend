"""LinkedIn OAuth v2 helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
_RUNTIME_LOG = Path(__file__).resolve().parents[3] / "linkedin_oauth_runtime.log"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_IDENTITY_ME_URL = "https://api.linkedin.com/rest/identityMe"
LINKEDIN_IDENTITY_ME_VERSION = "202510.03"

DEFAULT_SCOPES = "openid profile r_profile_basicinfo"
LINKEDIN_CALLBACK_PATH = "/api/v1/community/linkedin/callback"


def runtime_debug(message: str) -> None:
    """Always append to linkedin_oauth_runtime.log for local troubleshooting."""
    stamp = datetime.now(timezone.utc).isoformat()
    line = f"{stamp} {message}"
    logger.info(message)
    try:
        with _RUNTIME_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _redirect_uri_for_trusted_host(host_header: str, scheme: str) -> str | None:
    """Build callback URL from incoming Host / X-Forwarded-Host (trusted hubregistrar.com hosts)."""
    host = (host_header or "").split(",")[0].strip()
    if not host:
        return None

    hostname = host.split(":")[0].lower()
    local_hosts = {"127.0.0.1", "localhost"}
    if hostname in local_hosts:
        return f"{scheme.rstrip(':')}://{host.rstrip('/')}{LINKEDIN_CALLBACK_PATH}"

    # Primary brand host: hubregistrar.com. Legacy cobrother.com hosts are kept
    # as a transition alias so deprecated demo traffic keeps working until retirement.
    if (
        hostname == "hubregistrar.com"
        or hostname.endswith(".hubregistrar.com")
        or hostname == "cobrother.com"
        or hostname.endswith(".cobrother.com")
    ):
        safe_scheme = "https" if scheme.lower().startswith("https") else scheme
        return f"{safe_scheme}://{host.rstrip('/')}{LINKEDIN_CALLBACK_PATH}"

    return None


def resolve_linkedin_redirect_uri(
    *,
    request_host: str | None = None,
    request_scheme: str | None = None,
) -> str:
    """
    Resolve OAuth redirect_uri for LinkedIn.

    Prefer the public host on the incoming request (backend.hubregistrar.com/api/…)
    so it matches LinkedIn app settings, then explicit env, then BACKEND_BASE_URL.
    """
    if request_host:
        derived = _redirect_uri_for_trusted_host(
            request_host,
            request_scheme or "https",
        )
        if derived:
            return derived

    explicit = (settings.LINKEDIN_REDIRECT_URI or "").strip()
    if explicit:
        return explicit

    base = settings.BACKEND_BASE_URL.rstrip("/")
    return f"{base}{LINKEDIN_CALLBACK_PATH}"


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scopes,
        "prompt": "consent",
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(query)}"


def exchange_authorization_code_response(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            LINKEDIN_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        body = response.json()

    if not isinstance(body, dict):
        raise ValueError("LinkedIn token exchange failed: invalid response")
    return body


def fetch_openid_userinfo(access_token: str) -> dict[str, Any]:
    """Name, picture, subject — OpenID userinfo does not include public profile URL."""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise ValueError("LinkedIn userinfo response invalid")
    return data


def normalize_profile_url(url: str | None) -> str | None:
    if not url:
        return None
    raw = str(url).strip()
    if not raw.startswith("http"):
        return None
    if "linkedin.com" not in raw.lower():
        return None
    return raw.rstrip("/") + "/"


def canonicalize_linkedin_profile_url(url: str | None) -> str | None:
    normalized = normalize_profile_url(url)
    if not normalized:
        return None
    if "/in/" in normalized and "profile-thirdparty-redirect" not in normalized:
        return normalized

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(
                normalized,
                headers={"User-Agent": "Deltapreneur/1.0 (+https://www.deltapreneur.com)"},
            )
            final = normalize_profile_url(str(response.url))
            if final and "/in/" in final:
                return final
    except httpx.HTTPError as exc:
        logger.warning("LinkedIn profile redirect resolve failed for %s: %s", normalized, exc)

    return normalized


def vanity_to_profile_url(vanity: str) -> str:
    slug = vanity.strip().strip("/")
    return f"https://www.linkedin.com/in/{slug}/"


def extract_profile_url_from_identity_me(body: dict[str, Any]) -> tuple[str | None, str]:
    """Resolve profile URL from /rest/identityMe basicInfo block."""
    profile_url = body.get("basicInfo", {}).get("profileUrl")
    basic_info = body.get("basicInfo", {})
    if not isinstance(basic_info, dict):
        basic_info = {}

    if profile_url:
        normalized = canonicalize_linkedin_profile_url(str(profile_url))
        if normalized:
            return normalized, "identityMe_basicInfo_profileUrl"

    if not profile_url and "vanityName" in basic_info:
        vanity_name = basic_info["vanityName"]
        if isinstance(vanity_name, str) and vanity_name.strip():
            return vanity_to_profile_url(vanity_name), "identityMe_basicInfo_vanityName"

    logger.warning(
        "LinkedIn identityMe basicInfo missing profileUrl and vanityName; keys=%s",
        sorted(basic_info.keys()) if basic_info else [],
    )
    return None, "identityMe_none"


def _image_url_from_claim(value: Any) -> str | None:
    if isinstance(value, str) and value.strip().startswith("http"):
        return value.strip()
    if isinstance(value, dict):
        for key in ("croppedImage", "originalImage", "url", "displayImage", "downloadUrl"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip().startswith("http"):
                return nested.strip()
            if isinstance(nested, dict):
                download = nested.get("downloadUrl")
                if isinstance(download, str) and download.strip().startswith("http"):
                    return download.strip()
    return None


def fetch_linkedin_member_profile(
    access_token: str,
    *,
    id_token: str | None = None,
) -> dict[str, str | None]:
    del id_token

    userinfo = fetch_openid_userinfo(access_token)
    linked_in_id = str(userinfo.get("sub") or "").strip()
    if not linked_in_id:
        raise ValueError("LinkedIn userinfo missing subject")

    profile_url: str | None = None
    resolved_via = "identityMe_none"
    profile_picture: str | None = None
    background_picture: str | None = None
    identity_headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_IDENTITY_ME_VERSION,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            identity_response = client.get(
                LINKEDIN_IDENTITY_ME_URL,
                headers=identity_headers,
            )
    except httpx.HTTPError as exc:
        runtime_debug(f"LinkedIn identityMe request failed error={exc}")
        logger.warning("LinkedIn identityMe request failed: %s", exc)
        identity_response = None

    if identity_response is not None:
        runtime_debug(
            "LinkedIn identityMe raw response "
            f"status={identity_response.status_code} body={identity_response.text}",
        )

        if identity_response.status_code == 200:
            try:
                response_json = identity_response.json()
            except json.JSONDecodeError:
                response_json = None
                logger.warning("LinkedIn identityMe returned non-JSON body")

            if isinstance(response_json, dict):
                profile_url = response_json.get("basicInfo", {}).get("profileUrl")
                basic_info = response_json.get("basicInfo", {})
                if not isinstance(basic_info, dict):
                    basic_info = {}

                if profile_url:
                    profile_url = canonicalize_linkedin_profile_url(str(profile_url))
                    if profile_url:
                        resolved_via = "identityMe_basicInfo_profileUrl"

                if not profile_url and "vanityName" in basic_info:
                    vanity_name = basic_info["vanityName"]
                    if isinstance(vanity_name, str) and vanity_name.strip():
                        profile_url = vanity_to_profile_url(vanity_name)
                        resolved_via = "identityMe_basicInfo_vanityName"

                profile_picture = _image_url_from_claim(basic_info.get("profilePicture"))
                background_picture = _image_url_from_claim(basic_info.get("backgroundPicture"))

                if profile_url:
                    logger.info(
                        "LinkedIn member profile URL resolved via %s: %s",
                        resolved_via,
                        profile_url,
                    )
                else:
                    logger.error(
                        "LinkedIn identityMe returned no profile URL for subject=%s; "
                        "saving name/photo/linked_in_id only",
                        linked_in_id,
                    )
        else:
            logger.warning(
                "LinkedIn identityMe request failed status=%s",
                identity_response.status_code,
            )
            logger.error(
                "LinkedIn identityMe request failed for subject=%s; "
                "saving name/photo/linked_in_id only",
                linked_in_id,
            )

    picture = (
        str(userinfo.get("picture") or "").strip()
        or profile_picture
        or None
    )

    runtime_debug(
        f"LinkedIn member profile import complete subject={linked_in_id} "
        f"strategy={resolved_via} profile_url={profile_url or '(missing)'}",
    )

    return {
        "linked_in_id": linked_in_id,
        "name": str(userinfo.get("name") or "").strip() or None,
        "email": str(userinfo.get("email") or "").strip() or None,
        "profile_url": profile_url,
        "picture": picture,
        "background_picture": background_picture,
    }


def resolve_linkedin_profile_assets(
    access_token: str,
    userinfo: dict[str, Any] | None = None,
    *,
    id_token: str | None = None,
) -> dict[str, str | None]:
    """Backward-compatible wrapper used by tests and callback."""
    del userinfo, id_token
    profile = fetch_linkedin_member_profile(access_token)
    return {
        "profile_url": profile["profile_url"],
        "picture": profile["picture"],
        "background_picture": profile["background_picture"],
    }

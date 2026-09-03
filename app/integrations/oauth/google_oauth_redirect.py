"""Google OAuth 2.0 authorization-code flow (backend redirect)."""

from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings
from app.core.frontend_origins import google_oauth_redirect_uri_for_request


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "openid email profile "
    "https://www.googleapis.com/auth/calendar.events"
)
# Allow small PC clock drift vs Google servers (avoids "Token used too early").
GOOGLE_ID_TOKEN_CLOCK_SKEW_SECONDS = 60


def google_oauth_redirect_uri(request=None, stored_uri: str | None = None) -> str:
    if stored_uri and str(stored_uri).strip():
        return str(stored_uri).strip()
    return google_oauth_redirect_uri_for_request(request)


def build_google_authorization_url(
    state: str,
    *,
    redirect_uri: str | None = None,
) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri or google_oauth_redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_and_verify_id_token(
    code: str,
    *,
    redirect_uri: str | None = None,
) -> dict:
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri or google_oauth_redirect_uri(),
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.is_error:
            detail = response.text
            try:
                body = response.json()
                detail = body.get("error_description") or body.get("error") or detail
            except ValueError:
                pass
            raise ValueError(
                f"Google token exchange failed ({response.status_code}): {detail}"
            )
        token_payload = response.json()

    raw_id_token = token_payload.get("id_token")
    if not raw_id_token:
        raise ValueError("Google token response missing id_token")

    id_info = google_id_token.verify_oauth2_token(
        raw_id_token,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
        clock_skew_in_seconds=GOOGLE_ID_TOKEN_CLOCK_SKEW_SECONDS,
    )

    iss = id_info.get("iss")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("Invalid Google token issuer")

    raw_verified = id_info.get("email_verified", False)
    if isinstance(raw_verified, str):
        email_verified = raw_verified.strip().lower() in (
            "true",
            "1",
            "yes",
        )
    else:
        email_verified = bool(raw_verified)

    return {
        "profile": {
            "sub": id_info.get("sub"),
            "email": id_info.get("email"),
            "email_verified": email_verified,
            "given_name": id_info.get("given_name"),
            "family_name": id_info.get("family_name"),
            "picture": id_info.get("picture"),
        },
        "tokens": {
            "access_token": token_payload.get("access_token"),
            "refresh_token": token_payload.get("refresh_token"),
        },
    }

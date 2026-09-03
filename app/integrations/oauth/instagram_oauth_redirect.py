"""Instagram OAuth 2.0 authorization-code flow using Instagram Basic Display API."""

from urllib.parse import urlencode
import httpx
from app.core.config import settings

INSTAGRAM_AUTH_URL = "https://api.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_ME_URL = "https://graph.instagram.com/me"
SCOPES = "user_profile,user_media"


def instagram_oauth_redirect_uri() -> str:
    if settings.INSTAGRAM_REDIRECT_URI and settings.INSTAGRAM_REDIRECT_URI.strip():
        return settings.INSTAGRAM_REDIRECT_URI.strip()
    base = settings.BACKEND_BASE_URL.rstrip("/")
    return f"{base}/api/v1/auth/oauth/instagram/callback"


def build_instagram_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.INSTAGRAM_CLIENT_ID,
        "redirect_uri": instagram_oauth_redirect_uri(),
        "state": state,
        "scope": SCOPES,
        "response_type": "code",
    }
    return f"{INSTAGRAM_AUTH_URL}?{urlencode(params)}"


def exchange_code_and_get_instagram_profile(code: str) -> dict:
    data = {
        "client_id": settings.INSTAGRAM_CLIENT_ID,
        "client_secret": settings.INSTAGRAM_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": instagram_oauth_redirect_uri(),
        "code": code,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            INSTAGRAM_TOKEN_URL,
            data=data,
        )
        if response.is_error:
            raise ValueError(f"Instagram token exchange failed: {response.text}")
        token_payload = response.json()

    access_token = token_payload.get("access_token")
    user_id = token_payload.get("user_id")
    if not access_token:
        raise ValueError("Instagram token response missing access_token")

    # Get user profile info
    params = {
        "fields": "id,username",
        "access_token": access_token,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.get(INSTAGRAM_ME_URL, params=params)
        if response.is_error:
            raise ValueError(f"Instagram profile fetch failed: {response.text}")
        profile = response.json()

    return {
        "profile": {
            "id": profile.get("id") or user_id,
            "username": profile.get("username"),
            # No email is provided by Instagram Basic Display API
            "email": None,
        },
        "tokens": {
            "access_token": access_token,
        },
    }

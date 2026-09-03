"""Facebook OAuth 2.0 authorization-code flow."""

from urllib.parse import urlencode
import httpx
from app.core.config import settings

FACEBOOK_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
FACEBOOK_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
FACEBOOK_ME_URL = "https://graph.facebook.com/me"
SCOPES = "email public_profile"


def facebook_oauth_redirect_uri() -> str:
    if settings.FACEBOOK_REDIRECT_URI and settings.FACEBOOK_REDIRECT_URI.strip():
        return settings.FACEBOOK_REDIRECT_URI.strip()
    base = settings.BACKEND_BASE_URL.rstrip("/")
    return f"{base}/api/v1/auth/oauth/facebook/callback"


def build_facebook_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.FACEBOOK_CLIENT_ID,
        "redirect_uri": facebook_oauth_redirect_uri(),
        "state": state,
        "scope": SCOPES,
        "response_type": "code",
        "display": "page",
        "auth_type": "reauthenticate",
    }
    return f"{FACEBOOK_AUTH_URL}?{urlencode(params)}"


def exchange_code_and_get_facebook_profile(code: str) -> dict:
    data = {
        "code": code,
        "client_id": settings.FACEBOOK_CLIENT_ID,
        "client_secret": settings.FACEBOOK_CLIENT_SECRET,
        "redirect_uri": facebook_oauth_redirect_uri(),
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            FACEBOOK_TOKEN_URL,
            data=data,
        )
        if response.is_error:
            raise ValueError(f"Facebook token exchange failed: {response.text}")
        token_payload = response.json()

    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValueError("Facebook token response missing access_token")

    # Get user profile info
    params = {
        "fields": "id,name,email,first_name,last_name,picture",
        "access_token": access_token,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.get(FACEBOOK_ME_URL, params=params)
        if response.is_error:
            raise ValueError(f"Facebook profile fetch failed: {response.text}")
        profile = response.json()

    picture_url = None
    picture_data = profile.get("picture", {})
    if isinstance(picture_data, dict):
        picture_url = picture_data.get("data", {}).get("url")

    return {
        "profile": {
            "id": profile.get("id"),
            "email": profile.get("email"),
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "name": profile.get("name"),
            "picture": picture_url,
        },
        "tokens": {
            "access_token": access_token,
        },
    }

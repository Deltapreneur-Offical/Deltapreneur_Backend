"""LinkedIn OAuth 2.0 authorization-code flow (OIDC login redirect)."""

from urllib.parse import urlencode
import httpx
from app.core.config import settings
from app.core.frontend_origins import linkedin_oauth_redirect_uri_for_request
import logging

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = "openid profile email"


def linkedin_oauth_redirect_uri(request=None, stored_uri: str | None = None) -> str:
    if stored_uri and str(stored_uri).strip():
        return str(stored_uri).strip()
    return linkedin_oauth_redirect_uri_for_request(request)


def build_linkedin_authorization_url(
    state: str,
    *,
    redirect_uri: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": redirect_uri or linkedin_oauth_redirect_uri(),
        "state": state,
        "scope": SCOPES,
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"


def exchange_code_and_get_linkedin_profile(
    code: str,
    *,
    redirect_uri: str | None = None,
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or linkedin_oauth_redirect_uri(),
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "client_secret": settings.LINKEDIN_CLIENT_SECRET,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            LINKEDIN_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.is_error:
            logger.error(
                "LinkedIn token exchange failed: status=%s body=%s",
                response.status_code,
                response.text,
            )
            raise ValueError(f"LinkedIn token exchange failed: {response.text}")
        token_payload = response.json()

    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValueError("LinkedIn token response missing access_token")

    # Get user OpenID info
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.is_error:
            logger.error(
                "LinkedIn userinfo fetch failed: status=%s body=%s",
                response.status_code,
                response.text,
            )
            raise ValueError(f"LinkedIn userinfo fetch failed: {response.text}")
        userinfo = response.json()

    return {
        "profile": {
            "id": userinfo.get("sub"),
            "email": userinfo.get("email"),
            "first_name": userinfo.get("given_name"),
            "last_name": userinfo.get("family_name"),
            "name": userinfo.get("name"),
            "picture": userinfo.get("picture"),
        },
        "tokens": {
            "access_token": access_token,
        },
    }

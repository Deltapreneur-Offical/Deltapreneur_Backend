from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import app.controller.auth.auth_controller as auth_controller
from app.core.database import get_db
from app.main import app
from app.service.auth.auth_service import AuthService


@pytest.fixture
def auth_client():
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_linkedin_login_endpoint_redirects(auth_client) -> None:
    client, _ = auth_client
    with patch("app.controller.auth.auth_controller.settings") as mock_settings:
        mock_settings.LINKEDIN_CLIENT_ID = "linkedin-client-id"
        mock_settings.LINKEDIN_CLIENT_SECRET = "linkedin-client-secret"
        mock_settings.LINKEDIN_REDIRECT_URI = "http://localhost:8000/callback"
        response = client.get("/api/v1/auth/oauth/linkedin/login", follow_redirects=False)

    assert response.status_code == 302
    assert "linkedin.com/oauth/v2/authorization" in response.headers["location"]


def test_facebook_login_endpoint_redirects(auth_client) -> None:
    client, _ = auth_client
    with patch("app.controller.auth.auth_controller.settings") as mock_settings:
        mock_settings.FACEBOOK_CLIENT_ID = "facebook-client-id"
        mock_settings.FACEBOOK_CLIENT_SECRET = "facebook-client-secret"
        mock_settings.FACEBOOK_REDIRECT_URI = "http://localhost:8000/callback"
        response = client.get("/api/v1/auth/oauth/facebook/login", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert "facebook.com" in location
    assert "auth_type=reauthenticate" in location
    assert "display=page" in location


def test_instagram_login_endpoint_redirects(auth_client) -> None:
    client, _ = auth_client
    with patch("app.controller.auth.auth_controller.settings") as mock_settings:
        mock_settings.INSTAGRAM_CLIENT_ID = "instagram-client-id"
        mock_settings.INSTAGRAM_CLIENT_SECRET = "instagram-client-secret"
        mock_settings.INSTAGRAM_REDIRECT_URI = "http://localhost:8000/callback"
        response = client.get("/api/v1/auth/oauth/instagram/login", follow_redirects=False)

    assert response.status_code == 302
    assert "instagram.com" in response.headers["location"]


def test_spring_compat_linkedin_login_redirects(auth_client) -> None:
    client, _ = auth_client
    with patch("app.controller.auth.auth_controller.settings") as mock_settings:
        mock_settings.LINKEDIN_CLIENT_ID = "linkedin-client-id"
        mock_settings.LINKEDIN_CLIENT_SECRET = "linkedin-client-secret"
        mock_settings.LINKEDIN_REDIRECT_URI = "http://localhost:8000/callback"
        response = client.get("/oauth2/authorization/linkedin", follow_redirects=False)

    assert response.status_code == 302
    assert "linkedin.com/oauth/v2/authorization" in response.headers["location"]


def test_linkedin_login_uses_configured_callback_on_deltapreneur_host(auth_client) -> None:
    client, _ = auth_client
    delta_uri = "https://api.deltapreneur.com/api/v1/community/linkedin/callback"
    with patch("app.controller.auth.auth_controller.settings") as mock_settings, patch(
        "app.core.frontend_origins.settings"
    ) as origin_settings:
        mock_settings.LINKEDIN_CLIENT_ID = "linkedin-client-id"
        mock_settings.LINKEDIN_CLIENT_SECRET = "linkedin-client-secret"
        origin_settings.LINKEDIN_REDIRECT_URI = delta_uri
        origin_settings.LINKEDIN_REDIRECT_URI_HUBREGISTRAR = (
            "https://backend.hubregistrar.com/api/v1/community/linkedin/callback"
        )
        origin_settings.BACKEND_BASE_URL = "https://api.deltapreneur.com"
        response = client.get(
            "/oauth2/authorization/linkedin",
            headers={"host": "api.deltapreneur.com"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    redirect_uri = parse_qs(urlparse(response.headers["location"]).query)["redirect_uri"][0]
    assert redirect_uri == delta_uri


def test_linkedin_login_does_not_switch_to_hub_leftover_on_hub_host(auth_client) -> None:
    client, _ = auth_client
    delta_uri = "https://api.deltapreneur.com/api/v1/community/linkedin/callback"
    hub_uri = "https://backend.hubregistrar.com/api/v1/community/linkedin/callback"
    with patch("app.controller.auth.auth_controller.settings") as mock_settings, patch(
        "app.core.frontend_origins.settings"
    ) as origin_settings:
        mock_settings.LINKEDIN_CLIENT_ID = "linkedin-client-id"
        mock_settings.LINKEDIN_CLIENT_SECRET = "linkedin-client-secret"
        origin_settings.LINKEDIN_REDIRECT_URI = delta_uri
        origin_settings.LINKEDIN_REDIRECT_URI_HUBREGISTRAR = hub_uri
        origin_settings.BACKEND_BASE_URL = "https://api.deltapreneur.com"
        response = client.get(
            "/oauth2/authorization/linkedin",
            headers={"host": "backend.hubregistrar.com"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    redirect_uri = parse_qs(urlparse(response.headers["location"]).query)["redirect_uri"][0]
    assert redirect_uri == delta_uri
    assert redirect_uri != hub_uri


def test_google_oauth_redirect_does_not_include_tokens_in_query(auth_client) -> None:
    session_data = {
        "accessToken": "access-secret",
        "refreshToken": "refresh-secret",
        "profileComplete": True,
    }

    response = auth_controller._google_oauth_frontend_redirect(
        success=True,
        new_user=False,
        session_data=session_data,
        provider="google",
        include_tokens=True,
    )

    location = response.headers["location"]
    assert "token=" not in location
    assert "refreshToken=" not in location
    assert "success=1" in location


def _host_request(host: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"host", host.encode())],
            "client": ("127.0.0.1", 123),
            "server": ("test", 443),
        }
    )


def test_google_oauth_success_ignores_cobrother_origin_on_deltapreneur_host() -> None:
    response = auth_controller._google_oauth_frontend_redirect(
        success=True,
        session_data={"profileComplete": True},
        provider="google",
        return_origin="https://cobrother.com",
        request=_host_request("api.deltapreneur.com"),
    )
    location = response.headers["location"]
    assert "cobrother.com/auth/callback" not in location
    assert "token=" not in location


def test_google_oauth_success_returns_to_deltapreneur_when_host_matches() -> None:
    response = auth_controller._google_oauth_frontend_redirect(
        success=True,
        session_data={"profileComplete": True},
        provider="google",
        return_origin="https://deltapreneur.com",
        request=_host_request("api.deltapreneur.com"),
    )
    assert response.headers["location"].startswith(
        "https://deltapreneur.com/auth/callback"
    )

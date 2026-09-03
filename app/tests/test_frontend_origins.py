from __future__ import annotations

from unittest.mock import patch

from starlette.requests import Request

from app.core.frontend_origins import (
    allowed_frontend_return_origin,
    cookie_domain_for_request,
    gated_frontend_origin,
    google_oauth_redirect_uri_for_request,
    linkedin_oauth_redirect_uri_for_request,
)
from app.core.oauth_state import create_oauth_state, parse_oauth_state


def _request(host: str) -> Request:
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


def test_allow_list_accepts_cobrother_and_hubregistrar_apex() -> None:
    assert allowed_frontend_return_origin("https://cobrother.com") == "https://cobrother.com"
    assert (
        allowed_frontend_return_origin("https://www.hubregistrar.com/")
        == "https://www.hubregistrar.com"
    )


def test_allow_list_rejects_open_redirects_and_api_hosts() -> None:
    assert allowed_frontend_return_origin("https://evil.example") is None
    assert allowed_frontend_return_origin("javascript:alert(1)") is None
    assert (
        allowed_frontend_return_origin("https://backend.cobrother.com") is None
    )
    assert allowed_frontend_return_origin("https://cobrother.com.evil.com") is None


def test_oauth_state_preserves_signed_return_origin() -> None:
    state = create_oauth_state(
        "google",
        return_origin="https://hubregistrar.com",
        redirect_uri="https://backend.hubregistrar.com/api/v1/auth/oauth/google/callback",
    )
    payload = parse_oauth_state(state, provider="google")
    assert payload is not None
    assert payload["return_origin"] == "https://hubregistrar.com"
    assert payload["redirect_uri"].endswith("/api/v1/auth/oauth/google/callback")


def test_hubregistrar_return_origin_ignored_on_cobrother_api_host() -> None:
    origin = gated_frontend_origin(
        return_origin="https://hubregistrar.com",
        request=_request("backend.cobrother.com"),
    )
    assert origin is None


def test_hubregistrar_return_origin_honored_on_hub_api_host() -> None:
    origin = gated_frontend_origin(
        return_origin="https://hubregistrar.com",
        request=_request("backend.hubregistrar.com"),
    )
    assert origin == "https://hubregistrar.com"


def test_cobrother_return_origin_honored_on_cobrother_api_host() -> None:
    origin = gated_frontend_origin(
        return_origin="https://cobrother.com",
        request=_request("backend.cobrother.com"),
    )
    assert origin == "https://cobrother.com"


def test_cookie_domain_follows_request_host() -> None:
    with patch("app.core.frontend_origins.settings") as mock_settings:
        mock_settings.AUTH_COOKIE_DOMAIN = ".cobrother.com"
        assert cookie_domain_for_request(_request("backend.cobrother.com")) == ".cobrother.com"
        assert cookie_domain_for_request(_request("backend.hubregistrar.com")) == ".hubregistrar.com"


def test_google_redirect_uri_keeps_cobrother_default() -> None:
    cobrother_uri = (
        "https://backend.cobrother.com/api/v1/auth/oauth/google/callback"
    )
    hub_uri = "https://backend.hubregistrar.com/api/v1/auth/oauth/google/callback"
    with patch("app.core.frontend_origins.settings") as mock_settings:
        mock_settings.GOOGLE_OAUTH_REDIRECT_URI = cobrother_uri
        mock_settings.GOOGLE_OAUTH_REDIRECT_URI_HUBREGISTRAR = ""
        mock_settings.BACKEND_BASE_URL = "https://backend.cobrother.com"
        assert google_oauth_redirect_uri_for_request(_request("backend.cobrother.com")) == cobrother_uri
        assert google_oauth_redirect_uri_for_request(_request("backend.hubregistrar.com")) == cobrother_uri

        mock_settings.GOOGLE_OAUTH_REDIRECT_URI_HUBREGISTRAR = hub_uri
        assert google_oauth_redirect_uri_for_request(_request("backend.hubregistrar.com")) == hub_uri
        assert google_oauth_redirect_uri_for_request(_request("backend.cobrother.com")) == cobrother_uri


def test_linkedin_redirect_uri_keeps_cobrother_default_and_adds_hub() -> None:
    cobrother_uri = (
        "https://backend.cobrother.com/api/v1/community/linkedin/callback"
    )
    hub_uri = "https://backend.hubregistrar.com/api/v1/community/linkedin/callback"
    with patch("app.core.frontend_origins.settings") as mock_settings:
        mock_settings.LINKEDIN_REDIRECT_URI = cobrother_uri
        mock_settings.LINKEDIN_REDIRECT_URI_HUBREGISTRAR = ""
        mock_settings.BACKEND_BASE_URL = "https://backend.cobrother.com"
        assert (
            linkedin_oauth_redirect_uri_for_request(_request("backend.cobrother.com"))
            == cobrother_uri
        )
        assert (
            linkedin_oauth_redirect_uri_for_request(_request("backend.hubregistrar.com"))
            == hub_uri
        )

        mock_settings.LINKEDIN_REDIRECT_URI_HUBREGISTRAR = hub_uri
        assert (
            linkedin_oauth_redirect_uri_for_request(_request("backend.hubregistrar.com"))
            == hub_uri
        )
        assert (
            linkedin_oauth_redirect_uri_for_request(_request("backend.cobrother.com"))
            == cobrother_uri
        )

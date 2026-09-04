import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.auth_cookies import (
    CSRF_HEADER_NAME,
    CSRF_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
    attach_session_cookies,
    require_csrf_for_cookie_session,
)
from app.core.security import hash_otp_code


def test_hash_otp_code_is_deterministic() -> None:
    assert hash_otp_code("123456") == hash_otp_code("123456")
    assert hash_otp_code("123456") != hash_otp_code("654321")


def _request_with_cookies(cookies: dict, headers: dict | None = None) -> Request:
    header_items = []
    for key, value in (headers or {}).items():
        header_items.append((key.lower().encode(), value.encode()))
    scope = {
        "type": "http",
        "headers": header_items,
        "method": "POST",
        "path": "/",
    }
    request = Request(scope)
    request._cookies = cookies
    return request


def test_csrf_skipped_when_no_refresh_cookie() -> None:
    request = _request_with_cookies({})
    require_csrf_for_cookie_session(request)


def test_csrf_required_when_refresh_cookie_present() -> None:
    request = _request_with_cookies(
        {REFRESH_TOKEN_COOKIE: "rt", CSRF_TOKEN_COOKIE: "abc"},
    )
    with pytest.raises(HTTPException) as exc_info:
        require_csrf_for_cookie_session(request)
    assert exc_info.value.status_code == 403


def test_csrf_passes_with_matching_header() -> None:
    request = _request_with_cookies(
        {REFRESH_TOKEN_COOKIE: "rt", CSRF_TOKEN_COOKIE: "abc"},
        {CSRF_HEADER_NAME: "abc"},
    )
    require_csrf_for_cookie_session(request)


def _host_request(host: str) -> Request:
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


def test_session_cookies_use_deltapreneur_domain_on_api_host() -> None:
    from starlette.responses import Response

    response = Response()
    attach_session_cookies(
        response,
        access_token="access",
        refresh_token="refresh",
        request=_host_request("api.deltapreneur.com"),
    )
    cookies = response.headers.getlist("set-cookie")
    assert cookies
    assert any("domain=.deltapreneur.com" in item.lower() for item in cookies)
    assert all("samesite=lax" in item.lower() for item in cookies)
    assert all("domain=.cobrother.com" not in item.lower() for item in cookies)

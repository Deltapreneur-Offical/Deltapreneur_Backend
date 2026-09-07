from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from app.core import bot_protection
from app.core.bot_protection import (
    is_protected_post_path,
    turnstile_action_for_path,
    verify_turnstile_token,
)
from app.core.config import settings
from app.core.exceptions import AppException


def _request(path: str = "/api/v1/auth/login") -> Request:
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "203.0.113.10"
    request.url = MagicMock()
    request.url.path = path
    return request


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict):
        self._payload = payload
        self.posts: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, data=None):
        self.posts.append({"url": url, "data": data})
        return _FakeResponse(self._payload)


def test_turnstile_action_mapping() -> None:
    assert turnstile_action_for_path("/api/v1/auth/login") == "login"
    assert turnstile_action_for_path("/api/v1/auth/otp/send") == "login"
    assert turnstile_action_for_path("/api/v1/auth/resend-verification") == "login"
    assert turnstile_action_for_path("/api/v1/auth/register") == "register"
    assert turnstile_action_for_path("/api/v1/auth/register/otp/verify") == "register"
    assert turnstile_action_for_path("/api/v1/auth/forgot-password") == "forgot-password"
    assert turnstile_action_for_path("/api/v1/feedback") == "feedback"
    assert turnstile_action_for_path("/api/v1/becobrother") == "join"
    assert turnstile_action_for_path("/api/v1/virtual-assistant") == "virtual-assistant"


def test_virtual_assistant_is_protected_post() -> None:
    assert is_protected_post_path("/api/v1/virtual-assistant")


def test_production_hostnames_never_include_localhost(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "TURNSTILE_HOSTNAMES",
        "www.deltapreneur.com,localhost,127.0.0.1",
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    hosts = settings.turnstile_expected_hostnames()
    assert "www.deltapreneur.com" in hosts
    assert "localhost" not in hosts
    assert "127.0.0.1" not in hosts


@pytest.mark.asyncio
async def test_rejects_oversized_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "unit-test-secret")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(AppException) as exc:
        await verify_turnstile_token(_request(), "x" * 2049, expected_action="login")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_dev_dummy_token_bypasses_siteverify(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "unit-test-secret")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    with patch.object(bot_protection.httpx, "AsyncClient") as client_cls:
        await verify_turnstile_token(
            _request(),
            "1x00000000000000000000AA",
            expected_action="login",
        )
        client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_production_accepts_matching_action_and_hostname(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "unit-test-secret")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "TURNSTILE_HOSTNAMES",
        "www.deltapreneur.com,deltapreneur.com",
    )
    fake = _FakeClient(
        {
            "success": True,
            "action": "login",
            "hostname": "www.deltapreneur.com",
        }
    )
    with patch.object(bot_protection.httpx, "AsyncClient", return_value=fake):
        await verify_turnstile_token(_request(), "real-token", expected_action="login")
    assert fake.posts[0]["url"] == bot_protection.TURNSTILE_VERIFY_URL


@pytest.mark.asyncio
async def test_production_rejects_action_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "unit-test-secret")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "TURNSTILE_HOSTNAMES", "www.deltapreneur.com")
    fake = _FakeClient(
        {
            "success": True,
            "action": "register",
            "hostname": "www.deltapreneur.com",
        }
    )
    with patch.object(bot_protection.httpx, "AsyncClient", return_value=fake):
        with pytest.raises(AppException) as exc:
            await verify_turnstile_token(_request(), "real-token", expected_action="login")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_production_rejects_localhost_hostname(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "unit-test-secret")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "TURNSTILE_HOSTNAMES",
        "www.deltapreneur.com,localhost",
    )
    fake = _FakeClient(
        {
            "success": True,
            "action": "login",
            "hostname": "localhost",
        }
    )
    with patch.object(bot_protection.httpx, "AsyncClient", return_value=fake):
        with pytest.raises(AppException) as exc:
            await verify_turnstile_token(_request(), "real-token", expected_action="login")
    assert exc.value.status_code == 403

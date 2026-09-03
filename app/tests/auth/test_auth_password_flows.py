from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.entity.user.auth_provider import AuthProvider
from app.entity.user.user_role import UserRole
from app.main import app
from app.service.auth.auth_service import AuthService


@pytest.fixture
def auth_client():
    db = MagicMock()
    user = AppUser(
        email="auth-flow@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )

    def _override_db():
        yield db

    def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    try:
        with TestClient(app) as client:
            yield client, db, user
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_forgot_password_endpoint_calls_service_with_client_meta(auth_client) -> None:
    client, _, _ = auth_client
    with patch.object(
        AuthService,
        "forgot_password",
        new=AsyncMock(
            return_value={"success": True, "message": "generic"},
        ),
    ) as forgot_mock:
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "person@example.com"},
            headers={"user-agent": "pytest-agent"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    forgot_mock.assert_awaited_once()
    _, args, kwargs = forgot_mock.mock_calls[0]
    assert args[1] == "person@example.com"
    assert kwargs["user_agent"] == "pytest-agent"


def test_reset_password_endpoint_maps_token_and_password(auth_client) -> None:
    client, _, _ = auth_client
    with patch.object(
        AuthService,
        "reset_password",
        new=AsyncMock(return_value={"success": True, "message": "ok"}),
    ) as reset_mock:
        response = client.post(
            "/api/v1/auth/reset-password",
            json={"token": "token-123", "password": "Newpass123"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    reset_mock.assert_awaited_once()
    _, args, _ = reset_mock.mock_calls[0]
    assert args[1] == "token-123"
    assert args[2] == "Newpass123"


def test_resend_verification_endpoint(auth_client) -> None:
    client, _, _ = auth_client
    with patch.object(
        AuthService,
        "resend_verification_email",
        new=AsyncMock(return_value={"success": True, "message": "generic"}),
    ) as resend_mock:
        response = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "verify@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    resend_mock.assert_awaited_once()
    _, args, _ = resend_mock.mock_calls[0]
    assert args[1] == "verify@example.com"


def test_change_password_clears_session_cookies(auth_client) -> None:
    client, _, _ = auth_client
    with patch.object(
        AuthService,
        "change_password",
        new=AsyncMock(return_value={"success": True, "message": "changed"}),
    ):
        response = client.post(
            "/api/v1/auth/change-password",
            json={"currentPassword": "Oldpass1", "newPassword": "Newpass1"},
        )

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "").lower()
    # clear_session_cookies emits delete-cookie set-cookie headers
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie


def test_set_password_clears_session_cookies(auth_client) -> None:
    client, _, _ = auth_client
    with patch.object(
        AuthService,
        "set_password",
        new=AsyncMock(return_value={"success": True, "message": "set"}),
    ):
        response = client.post(
            "/api/v1/auth/set-password",
            json={"newPassword": "Newpass1"},
        )

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie


def test_verify_email_redirects_to_frontend_callback(auth_client) -> None:
    client, _, _ = auth_client
    with patch.object(
        AuthService,
        "verify_email",
        new=AsyncMock(
            return_value={
                "success": True,
                "data": {
                    "accessToken": "a-token",
                    "refreshToken": "r-token",
                    "profileComplete": True,
                    "newUser": False,
                },
            },
        ),
    ):
        response = client.get("/api/v1/auth/verify-email?token=abc123", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers.get("location", "")
    assert "success=1" in location
    assert "token=" not in location
    assert "refreshToken=" not in location
    assert "profileComplete=true" in location


@pytest.mark.asyncio
async def test_auth_service_set_password_rejects_when_password_exists() -> None:
    db = MagicMock()
    user = AppUser(
        email="exists@test.local",
        password="already-hashed",
        auth_provider=AuthProvider.EMAIL,
        active=True,
    )

    with pytest.raises(Exception) as exc:
        await AuthService.set_password(db, user, "Newpass1")

    assert "already set" in str(exc.value).lower()


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.service.auth.auth_service import AuthService


@pytest.fixture
def register_otp_client():
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_send_register_otp_endpoint_calls_service(register_otp_client) -> None:
    client, _ = register_otp_client
    with patch.object(
        AuthService,
        "send_otp_for_registration",
        new=AsyncMock(
            return_value={"success": True, "message": "Verification code sent."},
        ),
    ) as send_mock:
        response = client.post(
            "/api/v1/auth/register/otp/send",
            json={"email": "new@example.com", "password": "Secret123"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    send_mock.assert_awaited_once()


def test_verify_register_otp_endpoint_calls_service(register_otp_client) -> None:
    client, _ = register_otp_client
    with patch.object(
        AuthService,
        "verify_otp_and_register",
        new=AsyncMock(
            return_value={
                "success": True,
                "message": "Login successful",
                "data": {
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "userId": "user-id",
                    "email": "new@example.com",
                    "role": "USER",
                    "expiresIn": 3600000,
                    "newUser": True,
                    "emailVerified": True,
                    "profileComplete": False,
                },
            },
        ),
    ) as verify_mock:
        response = client.post(
            "/api/v1/auth/register/otp/verify",
            json={"email": "new@example.com", "otpCode": "123456"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    verify_mock.assert_awaited_once()


def test_resend_register_otp_endpoint_calls_service(register_otp_client) -> None:
    client, _ = register_otp_client
    with patch.object(
        AuthService,
        "resend_otp_for_registration",
        new=AsyncMock(
            return_value={"success": True, "message": "Code resent."},
        ),
    ) as resend_mock:
        response = client.post(
            "/api/v1/auth/register/otp/resend",
            json={"email": "new@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    resend_mock.assert_awaited_once()

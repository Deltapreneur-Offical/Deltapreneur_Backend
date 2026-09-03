"""Auth complete-profile and /me profile fields."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.main import app
from app.model.auth.complete_profile_request import CompleteProfileRequest
from app.repository.user_repository import UserRepository
from app.service.auth.auth_service import AuthService
from app.service.profile.profile_service import ProfileService
from app.utils.user_identity import resolved_username


def test_names_allow_profile_complete() -> None:
    assert AuthService._names_allow_profile_complete("Ada", "Lovelace") is True
    assert AuthService._names_allow_profile_complete("Ada", None) is False
    assert AuthService._names_allow_profile_complete("", "Lovelace") is False


def test_user_profile_payload_shape() -> None:
    user = AppUser(
        email="u@test.local",
        firstname="Ada",
        lastname="Lovelace",
        role=UserRole.USER,
        profile_complete=True,
        email_verified=True,
    )
    payload = AuthService.user_profile_payload(user)
    assert payload["profileComplete"] is True
    assert payload["firstname"] == "Ada"
    assert payload["lastname"] == "Lovelace"
    assert payload["username"] == "Ada Lovelace"
    assert "profileComplete" in payload
    assert "display_name" not in payload


@pytest.mark.asyncio
async def test_complete_profile_updates_user() -> None:
    user = AppUser(
        email="u@test.local",
        firstname=None,
        lastname=None,
        role=UserRole.USER,
        profile_complete=False,
        email_verified=True,
        active=True,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch.object(UserRepository, "save", return_value=user) as save_mock:
        result = await ProfileService.complete_profile(
            db,
            user,
            CompleteProfileRequest(
                firstname="  Ada ",
                lastname=" Lovelace ",
                phoneNumber="9876543210",
            ),
        )

    assert user.firstname == "Ada"
    assert user.lastname == "Lovelace"
    assert user.profile_complete is True
    assert result["success"] is True
    assert result["data"]["profileComplete"] is True
    assert result["data"]["firstname"] == "Ada"
    assert result["data"]["lastname"] == "Lovelace"
    save_mock.assert_called_once()


@pytest.mark.asyncio
async def test_complete_profile_accepts_phone_and_address() -> None:
    user = AppUser(
        email="u2@test.local",
        firstname=None,
        lastname=None,
        role=UserRole.USER,
        profile_complete=False,
        email_verified=True,
        active=True,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch.object(UserRepository, "save", return_value=user):
        await ProfileService.complete_profile(
            db,
            user,
            CompleteProfileRequest(
                firstname="Gekko",
                lastname="Reyna",
                phoneNumber="9876543210",
                address="Jayanagar, Bengaluru",
            ),
        )

    assert user.phone_number == "+919876543210"
    assert user.address == "Jayanagar, Bengaluru"
    assert user.profile_complete is True


def test_complete_profile_request_rejects_extra_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CompleteProfileRequest(
            firstname="A",
            lastname="B",
            unknownField="x",
        )


@pytest.mark.asyncio
async def test_auth_service_complete_profile_delegates_to_profile_service() -> None:
    user = AppUser(
        email="u@test.local",
        firstname=None,
        lastname=None,
        role=UserRole.USER,
        profile_complete=False,
        email_verified=True,
    )
    db = MagicMock()
    body = CompleteProfileRequest(
        firstname="Ada",
        lastname="Lovelace",
        phoneNumber="9876543210",
    )
    expected = {"success": True, "message": "ok", "data": {}}

    with patch.object(
        UserRepository,
        "find_by_email",
        return_value=user,
    ) as find_mock:
        with patch.object(
            ProfileService,
            "complete_profile",
            return_value=expected,
        ) as profile_mock:
            result = await AuthService.complete_profile(db, user.email, body)

    find_mock.assert_called_once()
    profile_mock.assert_called_once_with(db, user, body)
    assert result == expected


def test_resolved_username_from_names() -> None:
    user = AppUser(
        email="u@test.local",
        firstname="Aditya",
        lastname="kittur",
        username=None,
    )
    assert resolved_username(user) == "Aditya kittur"


def test_me_returns_profile_fields() -> None:
    user = AppUser(
        email="me@test.local",
        firstname="Test",
        lastname="User",
        role=UserRole.USER,
        profile_complete=False,
        email_verified=True,
    )

    def _override_user():
        return user

    app.dependency_overrides[get_current_user] = _override_user
    try:
        client = TestClient(app)
        response = client.get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["firstname"] == "Test"
    assert data["lastname"] == "User"
    assert data["profileComplete"] is False
    assert data["username"] == "Test User"
    assert "display_name" not in data

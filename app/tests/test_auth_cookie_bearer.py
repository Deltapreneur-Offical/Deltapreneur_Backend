from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth_cookies import ACCESS_TOKEN_COOKIE
from app.core.database import get_db
from app.core.security import create_access_token
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.main import app


@pytest.fixture
def me_client():
    user = AppUser(
        email="cookie-auth@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )
    user.id = uuid.uuid4()

    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            yield client, db, user
    finally:
        app.dependency_overrides.pop(get_db, None)


def _active_session(user: AppUser, session_id: uuid.UUID):
    token = MagicMock()
    token.user_id = user.id
    token.session_public_id = session_id
    token.revoked = False
    return [token]


def test_me_accepts_access_token_cookie(me_client) -> None:
    client, db, user = me_client
    session_id = uuid.uuid4()
    token = create_access_token(
        user.email,
        user.role.value,
        str(session_id),
    )

    with (
        patch(
            "app.core.dependencies.UserRepository.find_by_email",
            return_value=user,
        ),
        patch(
            "app.core.dependencies.RefreshTokenRepository.find_active_by_session",
            return_value=_active_session(user, session_id),
        ),
    ):
        client.cookies = {ACCESS_TOKEN_COOKIE: token}
        response = client.get(
            "/api/v1/auth/me",
        )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == user.email


def test_me_prefers_bearer_over_cookie(me_client) -> None:
    client, db, user = me_client
    other = AppUser(
        email="other@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )
    other.id = uuid.uuid4()
    bearer_session = uuid.uuid4()
    cookie_session = uuid.uuid4()
    bearer = create_access_token(
        user.email,
        user.role.value,
        str(bearer_session),
    )
    cookie = create_access_token(
        other.email,
        other.role.value,
        str(cookie_session),
    )

    with (
        patch(
            "app.core.dependencies.UserRepository.find_by_email",
            side_effect=lambda _db, email: user if email == user.email else other,
        ),
        patch(
            "app.core.dependencies.RefreshTokenRepository.find_active_by_session",
            side_effect=lambda _db, sid: (
                _active_session(user, bearer_session)
                if sid == bearer_session
                else _active_session(other, cookie_session)
            ),
        ),
    ):
        client.cookies = {ACCESS_TOKEN_COOKIE: cookie}
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {bearer}"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == user.email


def test_me_rejects_revoked_session(me_client) -> None:
    client, db, user = me_client
    session_id = uuid.uuid4()
    token = create_access_token(
        user.email,
        user.role.value,
        str(session_id),
    )

    with (
        patch(
            "app.core.dependencies.UserRepository.find_by_email",
            return_value=user,
        ),
        patch(
            "app.core.dependencies.RefreshTokenRepository.find_active_by_session",
            return_value=[],
        ),
    ):
        client.cookies = {ACCESS_TOKEN_COOKIE: token}
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401

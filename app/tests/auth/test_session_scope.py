"""Login may share one database with production without killing the other session.

These tests never open Postgres — they only exercise config + the login revoke
call. Logout / password-change still omit ``scope`` and revoke every session.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.core.config import Settings, settings
from app.entity.user.app_user import AppUser
from app.entity.user.refresh_token import RevocationReason
from app.entity.user.user_role import UserRole
from app.repository.refresh_token_repository import RefreshTokenRepository
from app.service.auth.auth_service import AuthService


def test_session_scope_follows_environment_when_unset() -> None:
    local = settings.model_copy(update={"ENVIRONMENT": "development", "SESSION_SCOPE": ""})
    prod = settings.model_copy(update={"ENVIRONMENT": "production", "SESSION_SCOPE": ""})
    assert local.resolved_session_scope() == "development"
    assert prod.resolved_session_scope() == "production"
    assert local.resolved_session_scope() != prod.resolved_session_scope()


def test_session_scope_explicit_override_wins() -> None:
    overridden = settings.model_copy(
        update={"ENVIRONMENT": "production", "SESSION_SCOPE": "local-dev"}
    )
    assert overridden.resolved_session_scope() == "local-dev"


def test_login_revokes_only_this_deployment_scope(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "SESSION_SCOPE", "")
    user = AppUser(
        email="scope@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
        is_deleted=False,
    )
    user.id = uuid.uuid4()
    captured: dict = {}

    def fake_revoke(db, target, reason, *, commit=True, scope=None):
        captured["scope"] = scope
        captured["reason"] = reason

    with (
        patch.object(RefreshTokenRepository, "revoke_all_user_tokens", side_effect=fake_revoke),
        patch.object(RefreshTokenRepository, "save", return_value=None),
        patch("app.service.auth.auth_service.create_access_token", return_value="access"),
        patch("app.service.auth.auth_service.generate_refresh_token", return_value="refresh"),
        patch("app.service.auth.auth_service.hash_refresh_token", return_value="hash"),
    ):
        AuthService._create_authenticated_session(MagicMock(), user)

    assert captured["reason"] == RevocationReason.LOGOUT
    assert captured["scope"] == "development"


def test_unscoped_revoke_still_available_for_password_change() -> None:
    """Safety: omitting scope must keep the previous 'revoke every session' path."""
    import inspect

    source = inspect.getsource(RefreshTokenRepository.revoke_all_user_tokens)
    assert "if scope is not None" in source
    assert "RefreshToken.device_name == scope" in source

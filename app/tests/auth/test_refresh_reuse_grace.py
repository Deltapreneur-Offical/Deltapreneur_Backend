"""Refresh rotation: overlapping refreshes must not kill a live session.

These tests mock the repository — they never open Postgres / RDS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.entity.user.app_user import AppUser
from app.entity.user.refresh_token import RevocationReason
from app.entity.user.user_role import UserRole
from app.service.auth.auth_exceptions import InvalidCredentialsException
from app.service.auth.auth_service import REFRESH_REUSE_GRACE, AuthService


def _user() -> AppUser:
    user = AppUser(
        email="refresh-race@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
        is_deleted=False,
    )
    user.id = uuid.uuid4()
    return user


def _token(
    *,
    user: AppUser,
    session_id: uuid.UUID,
    revoked: bool = False,
    reason=None,
    replaced_by=None,
    revoked_at=None,
    expires_at=None,
):
    token = MagicMock()
    token.id = uuid.uuid4()
    token.user = user
    token.user_id = user.id
    token.session_public_id = session_id
    token.revoked = revoked
    token.revocation_reason = reason
    token.replaced_by_token_id = replaced_by
    token.revoked_at = revoked_at
    token.expires_at = expires_at or (datetime.now(UTC) + timedelta(days=30))
    token.ip_address = None
    token.user_agent = None
    token.device_name = None
    return token


@pytest.mark.asyncio
async def test_overlapping_refresh_of_rotated_parent_does_not_revoke_chain() -> None:
    user = _user()
    session_id = uuid.uuid4()
    child = _token(user=user, session_id=session_id)
    parent = _token(
        user=user,
        session_id=session_id,
        revoked=True,
        reason=RevocationReason.ROTATED,
        replaced_by=child.id,
        revoked_at=datetime.now(UTC),
    )
    db = MagicMock()

    with (
        patch(
            "app.service.auth.auth_service.hash_refresh_token",
            return_value="hash",
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.find_by_token_hash",
            return_value=parent,
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.find_by_id",
            return_value=child,
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.revoke_session_chain",
        ) as revoke_chain,
        patch(
            "app.service.auth.auth_service.create_access_token",
            return_value="new-access",
        ),
    ):
        result = await AuthService.refresh_access_token(db, "parent-raw")

    assert result["success"] is True
    assert result["data"]["accessToken"] == "new-access"
    assert "refreshToken" not in result["data"]
    revoke_chain.assert_not_called()


@pytest.mark.asyncio
async def test_replay_after_grace_window_revokes_session_chain() -> None:
    user = _user()
    session_id = uuid.uuid4()
    child = _token(user=user, session_id=session_id)
    parent = _token(
        user=user,
        session_id=session_id,
        revoked=True,
        reason=RevocationReason.ROTATED,
        replaced_by=child.id,
        revoked_at=datetime.now(UTC) - REFRESH_REUSE_GRACE - timedelta(seconds=5),
    )
    db = MagicMock()

    with (
        patch(
            "app.service.auth.auth_service.hash_refresh_token",
            return_value="hash",
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.find_by_token_hash",
            return_value=parent,
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.find_by_id",
            return_value=child,
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.revoke_session_chain",
        ) as revoke_chain,
    ):
        with pytest.raises(InvalidCredentialsException, match="revoked"):
            await AuthService.refresh_access_token(db, "parent-raw")

    revoke_chain.assert_called_once()


@pytest.mark.asyncio
async def test_revoked_token_without_replacement_does_not_revoke_chain() -> None:
    user = _user()
    session_id = uuid.uuid4()
    parent = _token(
        user=user,
        session_id=session_id,
        revoked=True,
        reason=RevocationReason.LOGOUT,
        replaced_by=None,
        revoked_at=datetime.now(UTC),
    )
    db = MagicMock()

    with (
        patch(
            "app.service.auth.auth_service.hash_refresh_token",
            return_value="hash",
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.find_by_token_hash",
            return_value=parent,
        ),
        patch(
            "app.service.auth.auth_service.RefreshTokenRepository.revoke_session_chain",
        ) as revoke_chain,
    ):
        with pytest.raises(InvalidCredentialsException, match="revoked"):
            await AuthService.refresh_access_token(db, "logged-out-raw")

    revoke_chain.assert_not_called()

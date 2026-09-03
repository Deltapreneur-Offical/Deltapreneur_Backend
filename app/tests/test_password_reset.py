from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.security import generate_password_reset_token, hash_reset_token
from app.entity.user.app_user import AppUser
from app.entity.user.auth_provider import AuthProvider
from app.entity.user.password_reset_token import PasswordResetToken
from app.repository.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from app.repository.user_repository import UserRepository
from app.service.auth.auth_exceptions import InvalidPasswordResetTokenException
from app.service.auth.auth_service import (
    AuthService,
    FORGOT_PASSWORD_GENERIC_MESSAGE,
)


def test_generate_password_reset_token_length() -> None:
    token = generate_password_reset_token()
    assert len(token) >= 32


def test_hash_reset_token_is_deterministic() -> None:
    raw = "test-reset-token-value"
    assert hash_reset_token(raw) == hash_reset_token(raw)


@pytest.mark.asyncio
async def test_forgot_password_generic_when_user_missing() -> None:
    db = MagicMock()

    with patch.object(UserRepository, "find_by_email", return_value=None):
        result = await AuthService.forgot_password(
            db,
            "nobody@example.com",
        )

    assert result["success"] is True
    assert result["message"] == FORGOT_PASSWORD_GENERIC_MESSAGE


@pytest.mark.asyncio
async def test_forgot_password_skips_oauth_only_user() -> None:
    db = MagicMock()
    user = AppUser(
        email="oauth@example.com",
        password=None,
        auth_provider=AuthProvider.OAUTH,
        active=True,
    )

    with patch.object(UserRepository, "find_by_email", return_value=user):
        result = await AuthService.forgot_password(db, user.email)

    assert result["message"] == FORGOT_PASSWORD_GENERIC_MESSAGE
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reset_password_rejects_expired_token() -> None:
    db = MagicMock()
    user = AppUser(
        id=uuid4(),
        email="user@example.com",
        password="hashed",
        auth_provider=AuthProvider.EMAIL,
        active=True,
    )
    stored = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_reset_token("expired-token"),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        user=user,
    )

    with patch.object(
        PasswordResetTokenRepository,
        "find_by_token_hash",
        return_value=stored,
    ):
        with pytest.raises(InvalidPasswordResetTokenException):
            await AuthService.reset_password(
                db,
                "expired-token",
                "Newpass1",
            )

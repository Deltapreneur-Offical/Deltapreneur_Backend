from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import (
    access_token_invalidated_by_password_change,
    decode_token,
    extract_email,
)


def test_access_token_invalidated_when_issued_before_password_change() -> None:

    user = MagicMock()
    user.password_changed_at = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
    issued = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
    payload = {"iat": int(issued.timestamp())}

    assert access_token_invalidated_by_password_change(payload, user) is True


def test_access_token_not_invalidated_when_issued_after_password_change() -> None:

    user = MagicMock()
    user.password_changed_at = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
    issued = datetime(2026, 1, 11, 12, 0, 0, tzinfo=UTC)
    payload = {"iat": int(issued.timestamp())}

    assert access_token_invalidated_by_password_change(payload, user) is False


def test_access_token_not_invalidated_when_no_password_changed_at() -> None:

    user = MagicMock()
    user.password_changed_at = None
    payload = {"iat": 1700000000}

    assert access_token_invalidated_by_password_change(payload, user) is False


def test_decode_token_invalid_raises_http_exception() -> None:

    with pytest.raises(HTTPException) as exc_info:
        decode_token("not-a-valid-jwt")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired token"


def test_extract_email_missing_sub_raises_http_exception() -> None:

    with patch(
        "app.core.security.decode_token",
        return_value={"role": "ROLE_USER"},
    ):

        with pytest.raises(HTTPException) as exc_info:
            extract_email("ignored")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token missing subject"

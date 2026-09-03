"""Focused bypass-oriented checks for recent security hardenings."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.core.auth_cookies import CSRF_HEADER_NAME, CSRF_TOKEN_COOKIE, require_csrf_for_cookie_session
from app.core.dependencies import _resolve_current_user
from app.core.security import create_access_token
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.integrations.razorpay.client import assert_captured_payment_for_order
from app.integrations.s3.upload_service import validate_image
from app.service.cart.cart_service import _sanitize_client_cart_metadata
from app.utils.safe_http import (
    LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
    assert_safe_outbound_url,
)


def test_csrf_rejects_mismatched_header_cookie():
    request = MagicMock()
    request.cookies = {
        "access_token": "x",
        CSRF_TOKEN_COOKIE: "expected",
    }
    request.headers = {CSRF_HEADER_NAME: "wrong"}
    with pytest.raises(Exception) as exc:
        require_csrf_for_cookie_session(request)
    assert getattr(exc.value, "status_code", None) == 403


def test_csrf_accepts_matching_double_submit():
    request = MagicMock()
    request.cookies = {
        "access_token": "x",
        CSRF_TOKEN_COOKIE: "same-token",
    }
    request.headers = {CSRF_HEADER_NAME: "same-token"}
    require_csrf_for_cookie_session(request)


def test_ssrf_blocks_suffix_lookalike_and_private_literals():
    with pytest.raises(ValueError):
        assert_safe_outbound_url(
            "https://notlicdn.com/x.jpg",
            allowed_host_suffixes=LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
        )
    with pytest.raises(ValueError):
        assert_safe_outbound_url(
            "https://licdn.com.attacker.example/x.jpg",
            allowed_host_suffixes=LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
        )
    with pytest.raises(ValueError):
        assert_safe_outbound_url("https://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError):
        assert_safe_outbound_url("http://media.licdn.com/x.jpg")  # http blocked


def test_upload_rejects_svg_even_when_named_png():
    from fastapi import UploadFile
    from io import BytesIO

    f = UploadFile(filename="logo.png", file=BytesIO(b"<svg>"), headers={"content-type": "image/svg+xml"})
    with pytest.raises(Exception) as exc:
        validate_image(f)
    assert getattr(exc.value, "status_code", None) == 400


def test_upload_rejects_svg_extension_with_image_jpeg_type():
    from fastapi import UploadFile
    from io import BytesIO

    f = UploadFile(filename="evil.svg", file=BytesIO(b"x"), headers={"content-type": "image/jpeg"})
    with pytest.raises(Exception) as exc:
        validate_image(f)
    assert getattr(exc.value, "status_code", None) == 400


def test_upload_rejects_mismatched_magic_bytes():
    from fastapi import UploadFile
    from io import BytesIO

    # Declared JPEG but body is not a JPEG.
    f = UploadFile(
        filename="logo.jpg",
        file=BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        headers={"content-type": "image/jpeg"},
    )
    with pytest.raises(Exception) as exc:
        validate_image(f)
    assert getattr(exc.value, "status_code", None) == 400


def test_upload_accepts_real_png_magic_bytes():
    from fastapi import UploadFile
    from io import BytesIO

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    f = UploadFile(filename="logo.png", file=BytesIO(png), headers={"content-type": "image/png"})
    validate_image(f)


def test_cart_metadata_strips_reserved_checkout_keys():
    cleaned = _sanitize_client_cart_metadata(
        {
            "period": 2,
            "_checkout_razorpay_order_id": "order_hijack",
            "_fulfilled_razorpay_payment_id": "pay_hijack",
            "ok": "keep",
        }
    )
    assert cleaned == {"period": 2, "ok": "keep"}


def test_payment_assert_fails_closed_without_buyer_note():
    with (
        patch("app.integrations.razorpay.client._allow_dev_payment_bypass", return_value=False),
        patch(
            "app.integrations.razorpay.client.fetch_payment",
            return_value={
                "id": "pay_1",
                "order_id": "order_1",
                "status": "captured",
                "amount": 10000,
                "currency": "INR",
            },
        ),
        patch(
            "app.integrations.razorpay.client.fetch_order",
            return_value={
                "id": "order_1",
                "amount": 10000,
                "currency": "INR",
                "notes": {},
            },
        ),
    ):
        with pytest.raises(ValueError, match="missing buyer binding"):
            assert_captured_payment_for_order(
                payment_id="pay_1",
                order_id="order_1",
                expected_buyer_id=str(uuid.uuid4()),
            )


def test_payment_assert_rejects_amount_mismatch():
    with (
        patch("app.integrations.razorpay.client._allow_dev_payment_bypass", return_value=False),
        patch(
            "app.integrations.razorpay.client.fetch_payment",
            return_value={
                "id": "pay_1",
                "order_id": "order_1",
                "status": "captured",
                "amount": 1,
                "currency": "INR",
            },
        ),
        patch(
            "app.integrations.razorpay.client.fetch_order",
            return_value={
                "id": "order_1",
                "amount": 10000,
                "currency": "INR",
                "notes": {"buyerId": "buyer"},
            },
        ),
    ):
        with pytest.raises(ValueError, match="amount"):
            assert_captured_payment_for_order(
                payment_id="pay_1",
                order_id="order_1",
                expected_buyer_id="buyer",
            )


def test_access_token_rejected_when_session_refresh_expired():
    user = AppUser(
        email="sess@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )
    user.id = uuid.uuid4()
    session_id = uuid.uuid4()
    token = create_access_token(user.email, user.role.value, str(session_id))

    expired = MagicMock()
    expired.user_id = user.id
    expired.revoked = False
    expired.expires_at = datetime.now(UTC) - timedelta(minutes=1)

    db = MagicMock()
    with (
        patch(
            "app.core.dependencies.RefreshTokenRepository.find_active_by_session",
            return_value=[],  # repository filters expired out
        ),
        patch(
            "app.core.dependencies.UserRepository.find_by_email",
            return_value=user,
        ),
    ):
        with pytest.raises(Exception) as exc:
            _resolve_current_user(token, db)
        assert getattr(exc.value, "status_code", None) == 401

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main import app


client = TestClient(app)


def _fake_user(user_id=None, email="test@example.com"):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email=email,
        firstname="Test",
        lastname="User",
        is_deleted=False,
        active=True,
    )


def _fake_community(
    *,
    community_id=None,
    app_user_id=None,
    linked_in_id=None,
):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=community_id or uuid.uuid4(),
        app_user_id=app_user_id or uuid.uuid4(),
        linked_in_id=linked_in_id,
        name="Old Name",
        image_url=None,
        linked_in_profile_url=None,
        role=None,
        views=0,
        skills=None,
        industry=None,
        location=None,
        why_im_here=None,
        is_approved=False,
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
        created_at=now,
        updated_at=now,
    )


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_login():
    app.dependency_overrides.clear()


def test_linkedin_auth_returns_503_when_not_configured():
    user = _fake_user()

    _login_as(user)

    try:
        with patch.object(settings, "LINKEDIN_CLIENT_ID", None), patch.object(
            settings, "LINKEDIN_CLIENT_SECRET", None
        ), patch.object(settings, "LINKEDIN_REDIRECT_URI", None):
            response = client.get("/api/v1/community/linkedin/auth")

        assert response.status_code == 503
        body = response.json()
        assert body.get("message") == "LinkedIn OAuth is not configured" or body.get("error") == "LinkedIn OAuth is not configured"

    finally:
        _clear_login()


def test_linkedin_auth_url_success():
    user = _fake_user(email="test@example.com")

    _login_as(user)

    try:
        with patch.object(settings, "LINKEDIN_CLIENT_ID", "client-id"), patch.object(
            settings, "LINKEDIN_CLIENT_SECRET", "client-secret"
        ), patch.object(
            settings,
            "LINKEDIN_REDIRECT_URI",
            "http://127.0.0.1:8000/api/v1/community/linkedin/callback",
        ):
            response = client.get("/api/v1/community/linkedin/auth")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "LinkedIn authorization URL generated successfully"
        assert "https://www.linkedin.com/oauth/v2/authorization" in body["data"]["url"]
        assert "client_id=client-id" in body["data"]["url"]
        assert "response_type=code" in body["data"]["url"]
        assert (
            "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fv1%2Fcommunity%2Flinkedin%2Fcallback"
            in body["data"]["url"]
        )

    finally:
        _clear_login()


def test_linkedin_auth_url_uses_demo_host_when_forwarded():
    user = _fake_user(email="test@example.com")

    _login_as(user)

    try:
        with patch.object(settings, "LINKEDIN_CLIENT_ID", "client-id"), patch.object(
            settings, "LINKEDIN_CLIENT_SECRET", "client-secret"
        ), patch.object(
            settings,
            "LINKEDIN_REDIRECT_URI",
            "https://backend.cobrother.com/api/v1/community/linkedin/callback",
        ):
            response = client.get(
                "/api/v1/community/linkedin/auth",
                headers={
                    "host": "demo.cobrother.com",
                    "x-forwarded-host": "demo.cobrother.com",
                    "x-forwarded-proto": "https",
                },
            )

        assert response.status_code == 200
        url = response.json()["data"]["url"]
        assert (
            "redirect_uri=https%3A%2F%2Fdemo.cobrother.com%2Fapi%2Fv1%2Fcommunity%2Flinkedin%2Fcallback"
            in url
        )

    finally:
        _clear_login()


def test_linkedin_callback_success_redirects_to_frontend():
    profile_id = uuid.uuid4()

    with patch.object(
        settings,
        "FRONTEND_BASE_URL",
        "http://localhost:3000",
    ), patch(
        "app.controller.community.community_controller.CommunityService.handle_linkedin_oauth_callback",
        return_value=(profile_id, True),
    ):
        response = client.get(
            "/api/v1/community/linkedin/callback",
            params={
                "code": "sample-code",
                "state": "test%40example.com",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == f"http://localhost:3000/creator?linkedin=success&profileId={profile_id}"
    )


def test_linkedin_callback_uses_return_origin_from_state():
    from app.service.community.community_service import CommunityService

    profile_id = uuid.uuid4()
    state = CommunityService._encode_linkedin_oauth_state(
        email="test@example.com",
        redirect_uri="http://127.0.0.1:8000/api/v1/community/linkedin/callback",
        return_origin="http://127.0.0.1:5173",
    )

    with patch.object(
        settings,
        "FRONTEND_BASE_URL",
        "https://cobrother.com",
    ), patch.object(
        settings,
        "CORS_ALLOW_ORIGINS",
        "https://cobrother.com,http://127.0.0.1:5173",
    ), patch(
        "app.controller.community.community_controller.CommunityService.handle_linkedin_oauth_callback",
        return_value=(profile_id, True),
    ):
        response = client.get(
            "/api/v1/community/linkedin/callback",
            params={
                "code": "sample-code",
                "state": state,
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == f"http://127.0.0.1:5173/creator?linkedin=success&profileId={profile_id}"
    )


def test_linkedin_auth_url_includes_return_origin_in_state():
    from urllib.parse import parse_qs, urlparse

    from app.service.community.community_service import CommunityService

    user = _fake_user(email="test@example.com")

    _login_as(user)

    try:
        with patch.object(settings, "LINKEDIN_CLIENT_ID", "client-id"), patch.object(
            settings, "LINKEDIN_CLIENT_SECRET", "client-secret"
        ), patch.object(
            settings,
            "LINKEDIN_REDIRECT_URI",
            "http://127.0.0.1:8000/api/v1/community/linkedin/callback",
        ), patch.object(
            settings,
            "CORS_ALLOW_ORIGINS",
            "http://127.0.0.1:5173",
        ):
            response = client.get(
                "/api/v1/community/linkedin/auth",
                params={"return_origin": "http://127.0.0.1:5173"},
            )

        assert response.status_code == 200
        url = response.json()["data"]["url"]
        assert "state=" in url
        state = parse_qs(urlparse(url).query).get("state", [None])[0]
        assert state
        email, return_origin, _redirect = CommunityService._parse_linkedin_oauth_state_payload(state)
        assert email == "test@example.com"
        assert return_origin == "http://127.0.0.1:5173"

    finally:
        _clear_login()


def test_linkedin_callback_error_redirects_to_frontend():
    with patch.object(
        settings,
        "FRONTEND_BASE_URL",
        "http://localhost:3000",
    ), patch(
        "app.controller.community.community_controller.CommunityService.handle_linkedin_oauth_callback",
        side_effect=ValueError("LinkedIn failed"),
    ):
        response = client.get(
            "/api/v1/community/linkedin/callback",
            params={
                "code": "bad-code",
                "state": "test%40example.com",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert "http://localhost:3000/creator?linkedin_error=" in response.headers["location"]


def test_linkedin_service_callback_updates_profile_success():
    user = _fake_user(email="test@example.com")
    community = _fake_community(app_user_id=user.id)

    def save_side_effect(*args, **kwargs):
        if kwargs:
            return kwargs["community"]
        return args[1]

    with patch.object(settings, "LINKEDIN_CLIENT_ID", "client-id"), patch.object(
        settings, "LINKEDIN_CLIENT_SECRET", "client-secret"
    ), patch.object(
        settings,
        "LINKEDIN_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v1/community/linkedin/callback",
    ), patch(
        "app.service.community.community_service.UserRepository.find_by_email_insensitive",
        return_value=user,
    ), patch(
        "app.service.community.community_service.linkedin_oauth.exchange_authorization_code_response",
        return_value={
            "access_token": "access-token",
            "scope": "openid profile r_profile_basicinfo",
        },
    ), patch(
        "app.service.community.community_service.linkedin_oauth.fetch_linkedin_member_profile",
        return_value={
            "linked_in_id": "linkedin-user-id",
            "name": "LinkedIn User",
            "email": "test@example.com",
            "picture": "https://example.com/photo.jpg",
            "profile_url": "https://www.linkedin.com/in/linkedin-user/",
            "background_picture": None,
        },
    ), patch(
        "app.service.community.community_service.CommunityRepository.find_by_linked_in_id",
        return_value=None,
    ), patch(
        "app.service.community.community_service.CommunityRepository.clear_linked_in_id_from_other_users",
    ), patch(
        "app.service.community.community_service.CommunityRepository.find_any_by_app_user_id",
        return_value=community,
    ), patch(
        "app.service.community.community_service.CommunityRepository.save",
        side_effect=save_side_effect,
    ), patch(
        "app.service.community.community_service.NotificationService.notify",
    ):
        from app.service.community.community_service import CommunityService

        profile_id, profile_url_imported = CommunityService.handle_linkedin_oauth_callback(
            db=SimpleNamespace(),
            code="sample-code",
            state=(
                "test%40example.com|1710000000|"
                "http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fv1%2Fcommunity%2Flinkedin%2Fcallback"
            ),
        )

    assert profile_id == community.id
    assert profile_url_imported is True
    assert community.linked_in_id == "linkedin-user-id"
    assert community.name == "LinkedIn User"
    # example.com is not a LinkedIn CDN host — download is rejected and image_url
    # must stay unchanged (never store a raw external/CDN fallback).
    assert community.image_url is None
    assert community.linked_in_profile_url == "https://www.linkedin.com/in/linkedin-user/"


def test_decode_linkedin_oauth_state_roundtrip_signed():
    from app.service.community.community_service import CommunityService

    redirect = "https://backend.cobrother.com/api/v1/community/linkedin/callback"
    state = CommunityService._encode_linkedin_oauth_state(
        email="user@example.com",
        redirect_uri=redirect,
        return_origin="https://cobrother.com",
    )
    decoded = CommunityService._decode_linkedin_oauth_state(state)
    assert decoded == "user@example.com"

    email, return_origin, redirect_uri = CommunityService._parse_linkedin_oauth_state_payload(state)
    assert email == "user@example.com"
    assert return_origin == "https://cobrother.com"
    assert redirect_uri == redirect


def test_decode_linkedin_oauth_state_rejects_unsigned_payload():
    from app.service.community.community_service import CommunityService

    assert CommunityService._decode_linkedin_oauth_state("user@example.com|1710000000") == ""
    email, _origin, redirect_uri = CommunityService._parse_linkedin_oauth_state_payload(
        "user%40example.com|1710000000|https%3A%2F%2Fbackend.cobrother.com%2Fapi%2Fv1%2Fcommunity%2Flinkedin%2Fcallback"
    )
    assert email == ""
    assert redirect_uri is None

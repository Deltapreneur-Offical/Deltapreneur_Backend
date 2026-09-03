import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app


client = TestClient(app)


def _fake_user(user_id=None):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="test@example.com",
        is_deleted=False,
        active=True,
    )


def _fake_community(
    *,
    community_id=None,
    app_user_id=None,
    name="Chris Alexander",
    location="Bengaluru",
    skills="Python, FastAPI, PostgreSQL",
):
    return SimpleNamespace(
        id=community_id or uuid.uuid4(),
        linked_in_id=None,
        name=name,
        about="My software engineer biography.",
        image_url=None,
        linked_in_profile_url="https://linkedin.com/in/chris",
        role="EMPLOYEE",
        views=0,
        skills=skills,
        industry="TECHNOLOGY",
        location=location,
        why_im_here="To connect with startup builders",
        is_approved=False,
        app_user_id=app_user_id or uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
    )


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_login():
    app.dependency_overrides.clear()


def test_community_module_connected():
    response = client.get("/api/v1/community/test")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Creator module is connected successfully"
    assert body["data"]["module"] == "community"
    assert body["data"]["status"] == "ready"


def test_get_all_community_profiles():
    with patch(
        "app.service.community.community_service.CommunityRepository.find_all",
        return_value=[],
    ):
        response = client.get("/api/v1/community/all")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Creator profiles fetched successfully"
    assert isinstance(body["data"], list)
    assert body["data"] == []


def test_get_community_profile_success():
    user = _fake_user()
    community = _fake_community(
        app_user_id=user.id,
        name="Chris Alexander",
        location="Bengaluru",
        skills="Python, FastAPI, PostgreSQL",
    )
    community.expected_rate = "5000/month"
    community.why_im_here = "To connect with startup builders"
    community.linked_in_id = "linkedin-subject"

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_service.CommunityRepository.find_by_id",
            return_value=community,
        ), patch(
            "app.service.community.community_service.ProfileViewRepository.count_unique_viewers",
            return_value=0,
        ), patch(
            "app.service.community.community_service.record_community_profile_view",
        ):
            response = client.get(f"/api/v1/creator/{community.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["name"] == "Chris Alexander"

    finally:
        _clear_login()


def test_get_missing_community_profile_returns_404():
    user = _fake_user()
    missing_id = uuid.uuid4()

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_service.CommunityRepository.find_by_id",
            return_value=None,
        ):
            response = client.get(f"/api/v1/community/{missing_id}")

        assert response.status_code == 404

    finally:
        _clear_login()


def test_create_my_profile_success():
    user = _fake_user()

    _login_as(user)

    try:
        def save_side_effect(_db, community):
            return community

        with patch(
            "app.service.community.community_service.CommunityRepository.find_any_by_app_user_id",
            return_value=None,
        ), patch(
            "app.service.community.community_service.CommunityRepository.save",
            side_effect=save_side_effect,
        ):
            response = client.post(
                "/api/v1/community/my",
                json={
                    "name": "Chris Alexander",
                    "role": "EMPLOYEE",
                    "skills": "Python, FastAPI, PostgreSQL",
                    "industry": "TECHNOLOGY",
                    "location": "Bengaluru",
                    "why_im_here": "To connect with startup builders",
                    "linked_in_profile_url": "https://linkedin.com/in/chris",
                },
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Creator profile created successfully"
        assert body["data"]["name"] == "Chris Alexander"
        assert body["data"]["role"] == "EMPLOYEE"
        assert body["data"]["location"] == "Bengaluru"

    finally:
        _clear_login()


def test_create_my_profile_duplicate_returns_409():
    user = _fake_user()
    existing_profile = _fake_community(app_user_id=user.id)

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_service.CommunityRepository.find_any_by_app_user_id",
            return_value=existing_profile,
        ):
            response = client.post(
                "/api/v1/community/my",
                json={
                    "name": "Chris Alexander",
                    "role": "EMPLOYEE",
                },
            )

        assert response.status_code == 409

    finally:
        _clear_login()


def test_get_my_profile_success():
    user = _fake_user()
    profile = _fake_community(app_user_id=user.id)

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_service.CommunityRepository.find_all_by_app_user_id",
            return_value=[profile],
        ):
            response = client.get("/api/v1/community/my")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "My creator profile fetched successfully"
        assert body["data"]["name"] == "Chris Alexander"
        assert body["data"]["app_user_id"] == str(user.id)

    finally:
        _clear_login()


def test_get_my_profile_returns_null_when_missing():
    user = _fake_user()
    _login_as(user)

    try:
        with patch(
            "app.service.community.community_service.CommunityRepository.find_all_by_app_user_id",
            return_value=[],
        ):
            response = client.get("/api/v1/creator/my")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"] is None

    finally:
        _clear_login()


def test_update_profile_success():
    user = _fake_user()
    community_id = uuid.uuid4()
    profile = _fake_community(
        community_id=community_id,
        app_user_id=user.id,
    )

    _login_as(user)

    try:
        def save_side_effect(_db, community):
            return community

        with patch(
            "app.service.community.community_service.CommunityRepository.find_by_id",
            return_value=profile,
        ), patch(
            "app.service.community.community_service.CommunityRepository.save",
            side_effect=save_side_effect,
        ):
            response = client.put(
                f"/api/v1/community/{community_id}",
                json={
                    "location": "Bangalore",
                    "skills": "Python, FastAPI, PostgreSQL, WebSocket",
                },
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Creator profile updated successfully"
        assert body["data"]["location"] == "Bangalore"
        assert body["data"]["skills"] == "Python, FastAPI, PostgreSQL, WebSocket"

    finally:
        _clear_login()


def test_delete_profile_calls_soft_delete():
    user = _fake_user()
    community_id = uuid.uuid4()
    profile = _fake_community(
        community_id=community_id,
        app_user_id=user.id,
    )

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_service.CommunityRepository.find_by_id",
            return_value=profile,
        ), patch(
            "app.service.community.community_service.CommunityRepository.soft_delete",
        ) as soft_delete_mock:
            response = client.delete(f"/api/v1/community/{community_id}")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Creator profile deleted successfully"

        soft_delete_mock.assert_called_once()

    finally:
        _clear_login()


        

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.exc import ProgrammingError

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app


client = TestClient(app)


def _fake_user(user_id=None):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="test@example.com",
        firstname="Test",
        lastname="User",
        is_deleted=False,
        active=True,
    )


def _fake_like(
    *,
    user_id=None,
    like_type="COMMUNITY",
    entity_id=None,
):
    now = datetime.now(timezone.utc)

    user = _fake_user(user_id=user_id)

    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user.id,
        like_type=like_type,
        entity_id=entity_id or str(uuid.uuid4()),
        user=user,
        created_at=now,
        updated_at=now,
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
    )


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_login():
    app.dependency_overrides.clear()


def test_like_module_connected():
    response = client.get("/api/v1/likes/test")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Like module is connected successfully"
    assert body["data"]["module"] == "likes"
    assert body["data"]["status"] == "ready"


def test_toggle_like_creates_like_success():
    user = _fake_user()
    entity_id = str(uuid.uuid4())

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.find_by_user_type_entity",
            return_value=None,
        ), patch(
            "app.service.likes.like_service.LikeRepository.find_any_by_user_type_entity",
            return_value=None,
        ), patch(
            "app.service.likes.like_service.LikeRepository.save",
        ), patch(
            "app.service.likes.like_service.LikeRepository.count_by_type_entity",
            return_value=1,
        ):
            response = client.post(f"/api/v1/likes/COMMUNITY/{entity_id}/toggle")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Like status updated successfully"
        assert body["data"]["type"] == "COMMUNITY"
        assert body["data"]["entity_id"] == entity_id
        assert body["data"]["liked"] is True
        assert body["data"]["total_likes"] == 1

    finally:
        _clear_login()


def test_toggle_like_removes_existing_like_success():
    user = _fake_user()
    entity_id = str(uuid.uuid4())
    existing_like = _fake_like(
        user_id=user.id,
        like_type="COMMUNITY",
        entity_id=entity_id,
    )

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.find_by_user_type_entity",
            return_value=existing_like,
        ), patch(
            "app.service.likes.like_service.LikeRepository.soft_delete",
        ) as soft_delete_mock, patch(
            "app.service.likes.like_service.LikeRepository.count_by_type_entity",
            return_value=0,
        ):
            response = client.post(f"/api/v1/likes/COMMUNITY/{entity_id}/toggle")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["data"]["liked"] is False
        assert body["data"]["total_likes"] == 0

        soft_delete_mock.assert_called_once()

    finally:
        _clear_login()


def test_toggle_like_restores_soft_deleted_like_success():
    user = _fake_user()
    entity_id = str(uuid.uuid4())
    soft_deleted_like = _fake_like(
        user_id=user.id,
        like_type="DOMAIN",
        entity_id=entity_id,
    )
    soft_deleted_like.is_deleted = True

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.find_by_user_type_entity",
            return_value=None,
        ), patch(
            "app.service.likes.like_service.LikeRepository.find_any_by_user_type_entity",
            return_value=soft_deleted_like,
        ), patch(
            "app.service.likes.like_service.LikeRepository.restore",
        ) as restore_mock, patch(
            "app.service.likes.like_service.LikeRepository.count_by_type_entity",
            return_value=1,
        ):
            response = client.post(f"/api/v1/likes/DOMAIN/{entity_id}/toggle")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["data"]["liked"] is True
        assert body["data"]["total_likes"] == 1

        restore_mock.assert_called_once()

    finally:
        _clear_login()


def test_toggle_like_skips_notification_when_db_lookup_fails():
    user = _fake_user()
    entity_id = str(uuid.uuid4())

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.find_by_user_type_entity",
            return_value=None,
        ), patch(
            "app.service.likes.like_service.LikeRepository.find_any_by_user_type_entity",
            return_value=None,
        ), patch(
            "app.service.likes.like_service.LikeRepository.save",
        ), patch(
            "app.service.likes.like_service.LikeRepository.count_by_type_entity",
            return_value=1,
        ), patch(
            "app.service.likes.like_service.NotificationService.notify",
            side_effect=ProgrammingError("relation does not exist", None, None),
        ):
            response = client.post(f"/api/v1/likes/DOMAIN/{entity_id}/toggle")

        assert response.status_code == 200
        assert response.json()["data"]["liked"] is True
    finally:
        _clear_login()


def test_get_like_status_success():
    user = _fake_user()
    entity_id = str(uuid.uuid4())

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.exists_by_user_type_entity",
            return_value=True,
        ), patch(
            "app.service.likes.like_service.LikeRepository.count_by_type_entity",
            return_value=5,
        ):
            response = client.get(f"/api/v1/likes/COMMUNITY/{entity_id}/status")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Like status fetched successfully"
        assert body["data"]["liked"] is True
        assert body["data"]["total_likes"] == 5

    finally:
        _clear_login()


def test_get_my_liked_entities_success():
    user = _fake_user()
    entity_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.find_entity_ids_by_user_and_type",
            return_value=entity_ids,
        ):
            response = client.get("/api/v1/likes/COMMUNITY/my-liked")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "My liked entities fetched successfully"
        assert body["data"]["type"] == "COMMUNITY"
        assert body["data"]["entity_ids"] == entity_ids

    finally:
        _clear_login()


def test_get_users_who_liked_success():
    entity_id = str(uuid.uuid4())
    like = _fake_like(
        like_type="COMMUNITY",
        entity_id=entity_id,
    )
    user = _fake_user()

    _login_as(user)

    try:
        with patch(
            "app.service.likes.like_service.LikeRepository.find_by_type_entity",
            return_value=[like],
        ):
            response = client.get(f"/api/v1/likes/COMMUNITY/{entity_id}/who-liked")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Users who liked fetched successfully"
        assert body["data"]["type"] == "COMMUNITY"
        assert body["data"]["entity_id"] == entity_id
        assert body["data"]["total_likes"] == 1
        assert len(body["data"]["users"]) == 1
    finally:
        _clear_login()


def test_invalid_like_type_returns_422():
    user = _fake_user()
    entity_id = str(uuid.uuid4())

    _login_as(user)

    try:
        response = client.get(f"/api/v1/likes/INVALID/{entity_id}/status")

        assert response.status_code == 422

    finally:
        _clear_login()

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


def _fake_notification(
    *,
    notification_id=None,
    app_user_id=None,
    is_read=False,
):
    return SimpleNamespace(
        id=notification_id or uuid.uuid4(),
        app_user_id=app_user_id or uuid.uuid4(),
        notification_type="GENERAL",
        title="Test notification",
        message="This is a test notification",
        target_url="/community",
        is_read=is_read,
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


def test_notification_module_connected():
    response = client.get("/api/v1/notifications/test")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Notification module is connected successfully"
    assert body["data"]["module"] == "notifications"
    assert body["data"]["status"] == "ready"


def test_get_my_notifications_success():
    user = _fake_user()
    notification = _fake_notification(app_user_id=user.id)

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.find_by_user_id",
            return_value=[notification],
        ):
            response = client.get("/api/v1/notifications/my")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Notifications fetched successfully"
        assert len(body["data"]) == 1
        assert body["data"][0]["title"] == "Test notification"

    finally:
        _clear_login()


def test_get_unread_notifications_success():
    user = _fake_user()
    notification = _fake_notification(
        app_user_id=user.id,
        is_read=False,
    )

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.find_unread_by_user_id",
            return_value=[notification],
        ):
            response = client.get("/api/v1/notifications/unread")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Unread notifications fetched successfully"
        assert len(body["data"]) == 1
        assert body["data"][0]["is_read"] is False

    finally:
        _clear_login()


def test_get_unread_count_success():
    user = _fake_user()

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.count_unread_by_user_id",
            return_value=0,
        ):
            response = client.get("/api/v1/notifications/unread-count")

        assert response.status_code == 200
        assert response.json() == {"count": 0}

    finally:
        _clear_login()


def test_get_unread_count_returns_zero_when_empty():
    user = _fake_user()

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.count_unread_by_user_id",
            return_value=0,
        ):
            response = client.get("/api/v1/notifications/unread-count")

        assert response.status_code == 200
        assert response.json()["count"] == 0

    finally:
        _clear_login()


def test_mark_notification_as_read_success():
    user = _fake_user()
    notification_id = uuid.uuid4()
    notification = _fake_notification(
        notification_id=notification_id,
        app_user_id=user.id,
        is_read=False,
    )

    _login_as(user)

    try:
        def save_side_effect(**kwargs):
            return kwargs["notification"]

        with patch(
            "app.service.notification.notification_service.NotificationRepository.find_by_id_and_user_id",
            return_value=notification,
        ), patch(
            "app.service.notification.notification_service.NotificationRepository.save",
            side_effect=save_side_effect,
        ):
            response = client.put(
                f"/api/v1/notifications/{notification_id}/read"
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Notification marked as read successfully"
        assert body["data"]["is_read"] is True

    finally:
        _clear_login()


def test_mark_missing_notification_as_read_returns_404():
    user = _fake_user()
    notification_id = uuid.uuid4()

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.find_by_id_and_user_id",
            return_value=None,
        ):
            response = client.put(
                f"/api/v1/notifications/{notification_id}/read"
            )

        assert response.status_code == 404

    finally:
        _clear_login()


def test_mark_all_notifications_as_read_success():
    user = _fake_user()

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.mark_all_read",
            return_value=3,
        ):
            response = client.put("/api/v1/notifications/read-all")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "All notifications marked as read successfully"
        assert body["data"]["updated_count"] == 3

    finally:
        _clear_login()


def test_delete_notification_success():
    user = _fake_user()
    notification_id = uuid.uuid4()
    notification = _fake_notification(
        notification_id=notification_id,
        app_user_id=user.id,
    )

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.find_by_id_and_user_id",
            return_value=notification,
        ), patch(
            "app.service.notification.notification_service.NotificationRepository.soft_delete",
        ) as soft_delete_mock:
            response = client.delete(
                f"/api/v1/notifications/{notification_id}"
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Notification deleted successfully"

        soft_delete_mock.assert_called_once()

    finally:
        _clear_login()


def test_delete_selected_notifications_success():
    user = _fake_user()
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.soft_delete_selected",
            return_value=2,
        ) as soft_delete_selected_mock:
            response = client.post(
                "/api/v1/notifications/delete-multiple",
                json={"ids": [id1, id2]},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["deleted_count"] == 2
        soft_delete_selected_mock.assert_called_once()

    finally:
        _clear_login()


def test_delete_all_notifications_success():
    user = _fake_user()

    _login_as(user)

    try:
        with patch(
            "app.service.notification.notification_service.NotificationRepository.soft_delete_all",
            return_value=5,
        ) as soft_delete_all_mock:
            response = client.delete("/api/v1/notifications/delete-all")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["deleted_count"] == 5
        soft_delete_all_mock.assert_called_once()

    finally:
        _clear_login()

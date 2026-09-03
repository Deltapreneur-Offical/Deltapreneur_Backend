import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.websocket.manager import notification_connection_manager


client = TestClient(app)


def _clear_notification_connections():
    notification_connection_manager.active_connections.clear()
    notification_connection_manager._user_connections.clear()


def _connection_rejected(url: str) -> bool:
    """
    True when the socket is rejected for auth.

    The notification endpoint accepts first, then closes with 4401/4403 on
    failure (so browsers get a real close code). Rejection therefore means:
    handshake may succeed, but the socket is never registered and the server
    closes immediately.
    """
    try:
        with client.websocket_connect(url) as websocket:
            if notification_connection_manager.active_connections:
                return False
            try:
                websocket.receive_text()
            except WebSocketDisconnect:
                return True
            except Exception:
                return True
            return False
    except Exception:
        return True


def test_notification_socket_rejects_connection_without_token():
    user_id = uuid.uuid4()
    _clear_notification_connections()

    rejected = _connection_rejected(
        f"/ws/notifications/{user_id}"
    )

    assert rejected is True
    assert len(notification_connection_manager.active_connections) == 0


def test_notification_socket_rejects_token_for_different_user():
    requested_user_id = uuid.uuid4()
    authenticated_user_id = uuid.uuid4()
    _clear_notification_connections()

    with patch(
        "app.websocket.notification_socket._resolve_user_id",
        new=AsyncMock(return_value=authenticated_user_id),
    ):
        rejected = _connection_rejected(
            f"/ws/notifications/{requested_user_id}?token=valid-user-2-token"
        )

    assert rejected is True
    assert len(notification_connection_manager.active_connections) == 0


def test_notification_socket_accepts_matching_authenticated_user():
    user_id = uuid.uuid4()
    _clear_notification_connections()

    with patch(
        "app.websocket.notification_socket._resolve_user_id",
        new=AsyncMock(return_value=user_id),
    ):
        with client.websocket_connect(
            f"/ws/notifications/{user_id}?token=valid-user-1-token"
        ):
            response = client.get("/api/v1/ws/status")

            assert response.status_code == 200

            data = response.json()["data"]

            assert data["notification_connections"] == 1
            assert str(user_id) in data["notification_users"]

    _clear_notification_connections()


def test_notification_socket_disconnect_removes_connection():
    user_id = uuid.uuid4()
    _clear_notification_connections()

    with patch(
        "app.websocket.notification_socket._resolve_user_id",
        new=AsyncMock(return_value=user_id),
    ):
        with client.websocket_connect(
            f"/ws/notifications/{user_id}?token=valid-token"
        ):
            assert len(notification_connection_manager.active_connections) == 1

    assert len(notification_connection_manager.active_connections) == 0
    assert str(user_id) not in notification_connection_manager._user_connections

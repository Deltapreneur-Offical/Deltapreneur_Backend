from fastapi.testclient import TestClient

from app.main import app
from app.websocket.manager import (
    community_auction_connection_manager,
    notification_connection_manager,
)


client = TestClient(app)


def test_websocket_module_connected():
    response = client.get("/api/v1/ws/test")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "WebSocket module is connected successfully"
    assert body["data"]["module"] == "websocket"
    assert body["data"]["status"] == "ready"


def test_websocket_status_success():
    notification_connection_manager.active_connections.clear()
    community_auction_connection_manager.active_connections.clear()

    response = client.get("/api/v1/ws/status")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "WebSocket status fetched successfully"
    assert body["data"]["notification_connections"] == 0
    assert body["data"]["notification_users"] == []
    assert body["data"]["community_auction_connections"] == 0
    assert body["data"]["community_auction_rooms"] == []
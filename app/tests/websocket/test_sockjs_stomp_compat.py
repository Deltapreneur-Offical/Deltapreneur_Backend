from fastapi.testclient import TestClient

from app.main import app
from app.websocket.stomp_sockjs_compat import _destinations_for_room


client = TestClient(app)


def test_sockjs_info_endpoint_available():
    res = client.get("/ws/info")
    assert res.status_code == 200
    body = res.json()
    assert body["websocket"] is True
    assert "entropy" in body


def test_stomp_handshake_connects():
    with client.websocket_connect("/ws/000/000/websocket") as ws:
        ws.send_text("CONNECT\naccept-version:1.2\n\n\x00")
        frame = ws.receive_text()
        assert frame.startswith("CONNECTED\n")


def test_destination_mapping_for_auction_rooms():
    assert _destinations_for_room("abc-123") == ["/topic/auction/abc-123"]
    assert _destinations_for_room("community_auction_abc-123") == [
        "/topic/community-auction/abc-123",
    ]

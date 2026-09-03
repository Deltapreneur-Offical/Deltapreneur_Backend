import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.websocket.stomp_sockjs_compat import _parse_stomp_frames, broadcast_room_compat


client = TestClient(app)


def test_sockjs_info_options_has_cors_headers():
    res = client.options("/ws/info")
    assert res.status_code == 204
    assert res.headers.get("Access-Control-Allow-Origin") == "*"
    assert "OPTIONS" in (res.headers.get("Access-Control-Allow-Methods") or "")


def test_parse_stomp_frames_handles_multiple_frames():
    raw = (
        "CONNECT\naccept-version:1.2\n\n\x00"
        "SUBSCRIBE\ndestination:/topic/auction/123\n\n\x00"
    )
    frames = _parse_stomp_frames(raw)
    assert len(frames) == 2
    assert frames[0][0] == "CONNECT"
    assert frames[1][0] == "SUBSCRIBE"
    assert frames[1][1]["destination"] == "/topic/auction/123"


def test_stomp_ping_receives_pong():
    with client.websocket_connect("/ws/100/200/websocket") as ws:
        ws.send_text("CONNECT\naccept-version:1.2\n\n\x00")
        assert ws.receive_text().startswith("CONNECTED")
        ws.send_text("PING\n\n\x00")
        assert ws.receive_text().startswith("PONG")


def test_stomp_subscribe_receives_broadcast_message():
    with client.websocket_connect("/ws/100/201/websocket") as ws:
        ws.send_text("CONNECT\naccept-version:1.2\n\n\x00")
        assert ws.receive_text().startswith("CONNECTED")
        ws.send_text("SUBSCRIBE\ndestination:/topic/auction/abc-room\n\n\x00")

        delivered = asyncio.run(
            broadcast_room_compat("abc-room", {"type": "BID_PLACED", "amount": 1234}),
        )
        assert delivered >= 1

        frame = ws.receive_text()
        assert frame.startswith("MESSAGE")
        assert "destination:/topic/auction/abc-room" in frame
        assert '"type":"BID_PLACED"' in frame


def test_stomp_subscribe_community_auction_topic():
    with client.websocket_connect("/ws/100/202/websocket") as ws:
        ws.send_text("CONNECT\naccept-version:1.2\n\n\x00")
        assert ws.receive_text().startswith("CONNECTED")
        ws.send_text(
            "SUBSCRIBE\ndestination:/topic/community-auction/abc-room\n\n\x00"
        )

        delivered = asyncio.run(
            broadcast_room_compat(
                "community_auction_abc-room",
                {"type": "BID_PLACED", "currentHighestBid": 99},
            ),
        )
        assert delivered >= 1

        frame = ws.receive_text()
        assert frame.startswith("MESSAGE")
        assert "destination:/topic/community-auction/abc-room" in frame
        assert '"type":"BID_PLACED"' in frame


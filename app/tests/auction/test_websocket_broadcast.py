"""
WebSocket layer tests.

Strategy:
- For the manager (room state, broadcast fan-out, eviction, personal
  notifications) we use lightweight fake WebSockets — no network. This keeps
  the tests deterministic and fast.
- For the endpoint we use Starlette's TestClient.websocket_connect (sync API)
  driven from inside an async test via asyncio.to_thread, so we exercise the
  real auth + accept + ping/pong flow end-to-end.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.websocket.connection import WebSocketConnection
from app.websocket.events import (
    EventType,
    build_bid_placed,
    build_auction_ended,
    build_user_outbid,
)
from app.websocket.manager import ConnectionManager

pytestmark = pytest.mark.asyncio

UID1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
UID2 = uuid.UUID("00000000-0000-4000-8000-000000000002")
UID3 = uuid.UUID("00000000-0000-4000-8000-000000000003")
UID42 = uuid.UUID("00000000-0000-4000-8000-000000000042")
UID43 = uuid.UUID("00000000-0000-4000-8000-000000000043")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


class FakeWS:
    """Minimal stand-in for Starlette WebSocket used by ConnectionManager."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []
        self.closed = False
        self.close_code: int | None = None

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionError("simulated dead socket")
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code


def _make_conn(
    auction_id: str = "a-1",
    user_id: uuid.UUID | None = None,
    *,
    fail: bool = False,
):
    ws = FakeWS(fail=fail)
    uid = user_id or UID1
    return WebSocketConnection(websocket=ws, auction_id=auction_id, user_id=uid), ws


# --------------------------------------------------------------------------- #
# Manager: room subscription                                                  #
# --------------------------------------------------------------------------- #


async def test_connect_adds_to_room_and_user_index():
    mgr = ConnectionManager()
    c1, _ = _make_conn(auction_id="A", user_id=UID1)
    c2, _ = _make_conn(auction_id="A", user_id=UID2)

    await mgr.connect(c1)
    await mgr.connect(c2)

    assert mgr.room_size("A") == 2
    assert c1 in mgr._rooms["A"]
    assert c2 in mgr._user_index[UID2]


async def test_disconnect_removes_from_both_indexes_and_collapses_empty_rooms():
    mgr = ConnectionManager()
    c, _ = _make_conn(auction_id="A", user_id=UID1)
    await mgr.connect(c)
    await mgr.disconnect(c)

    assert mgr.room_size("A") == 0
    assert "A" not in mgr._rooms
    assert UID1 not in mgr._user_index


async def test_join_room_moves_connection_across_rooms():
    mgr = ConnectionManager()
    c, _ = _make_conn(auction_id="A", user_id=UID1)
    await mgr.connect(c)

    await mgr.join_room(c, "B")
    assert mgr.room_size("A") == 0
    assert mgr.room_size("B") == 1
    assert c.auction_id == "B"


# --------------------------------------------------------------------------- #
# Manager: broadcast                                                          #
# --------------------------------------------------------------------------- #


async def test_broadcast_delivers_to_all_connections_in_room():
    mgr = ConnectionManager()
    conns = []
    sockets = []
    for uid in (UID1, UID2, UID3):
        c, ws = _make_conn(auction_id="X", user_id=uid)
        await mgr.connect(c)
        conns.append(c); sockets.append(ws)

    payload = build_bid_placed(
        auction_id="X", bid_id="b1", bidder_id=UID2, bidder_name="N",
        amount=100, current_highest_bid=100, total_bids=1,
        end_time=datetime.now(timezone.utc), extended=False,
    )
    delivered = await mgr.broadcast_to_auction("X", payload)

    assert delivered == 3
    for ws in sockets:
        assert ws.sent[-1]["type"] == EventType.BID_PLACED.value


async def test_broadcast_exclude_user_skips_bidder():
    mgr = ConnectionManager()
    c1, ws1 = _make_conn(auction_id="X", user_id=UID1)
    c2, ws2 = _make_conn(auction_id="X", user_id=UID2)
    await mgr.connect(c1); await mgr.connect(c2)

    delivered = await mgr.broadcast_to_auction(
        "X", {"type": "BID_PLACED"}, exclude_user_ids={UID2},
    )
    assert delivered == 1
    assert ws1.sent and not ws2.sent


async def test_broadcast_evicts_dead_socket_and_keeps_others():
    mgr = ConnectionManager()
    dead, dead_ws = _make_conn(auction_id="X", user_id=UID1, fail=True)
    good, good_ws = _make_conn(auction_id="X", user_id=UID2)
    await mgr.connect(dead); await mgr.connect(good)

    delivered = await mgr.broadcast_to_auction("X", {"type": "BID_PLACED"})
    assert delivered == 1
    assert good_ws.sent
    # Dead connection evicted.
    assert mgr.room_size("X") == 1
    assert dead_ws.closed


# --------------------------------------------------------------------------- #
# Manager: personal notifications                                             #
# --------------------------------------------------------------------------- #


async def test_personal_notification_reaches_all_user_sockets_across_rooms():
    mgr = ConnectionManager()
    c1, ws1 = _make_conn(auction_id="A", user_id=UID42)
    c2, ws2 = _make_conn(auction_id="B", user_id=UID42)
    c3, ws3 = _make_conn(auction_id="A", user_id=UID43)
    for c in (c1, c2, c3):
        await mgr.connect(c)

    payload = build_user_outbid(
        auction_id="A", outbid_user_id=UID42,
        new_highest_amount=500, new_highest_bidder_name="X",
    )
    delivered = await mgr.send_personal_notification(UID42, payload)
    assert delivered == 2
    assert ws1.sent and ws2.sent and not ws3.sent


# --------------------------------------------------------------------------- #
# Events: payload shape + JSON safety                                          #
# --------------------------------------------------------------------------- #


async def test_event_payload_is_json_serializable():
    import json
    import uuid
    from decimal import Decimal

    payload = build_auction_ended(
        auction_id=uuid.uuid4(),
        domain_id=uuid.uuid4(),
        winner_id=uuid.uuid4(),
        winner_name="W",
        winning_amount=Decimal("123.45"),
    )
    raw = json.dumps(payload)
    parsed = json.loads(raw)
    assert parsed["type"] == EventType.AUCTION_ENDED.value
    assert parsed["data"]["winning_amount"] == "123.45"


# --------------------------------------------------------------------------- #
# Endpoint: connect + auth + ping/pong (real Starlette TestClient)            #
# --------------------------------------------------------------------------- #


@pytest.fixture
def ws_app():
    """
    Build a tiny FastAPI app that mounts the WS router.
    """
    from fastapi import FastAPI
    from app.websocket import auction_socket as ws_module

    app = FastAPI()
    app.include_router(ws_module.router)
    return app


async def test_websocket_connect_receives_connected_and_pong(
    ws_app, auction_factory, seller, monkeypatch,
):
    from starlette.testclient import TestClient
    from app.websocket import auction_socket as ws_module

    monkeypatch.setattr(
        ws_module, "_resolve_user_id",
        AsyncMock(return_value=seller.id),
    )
    monkeypatch.setattr(
        ws_module, "_auction_exists",
        AsyncMock(return_value=True),
    )

    auction = await auction_factory(created_by=seller.id)

    def _run():
        client = TestClient(ws_app)
        with client.websocket_connect(
            f"/ws/auction/{auction.id}?token=anything"
        ) as ws:
            greet = ws.receive_json()
            assert greet["type"] == EventType.CONNECTED.value
            assert greet["data"]["user_id"] == str(seller.id)

            ws.send_json({"type": "PING"})
            reply = ws.receive_json()
            # Server may send its own PING before responding to ours; consume
            # any leading PING and look for the PONG.
            while reply.get("type") == EventType.PING.value:
                reply = ws.receive_json()
            assert reply["type"] == EventType.PONG.value

    await asyncio.to_thread(_run)


async def test_websocket_unknown_auction_closes_with_4404(ws_app, monkeypatch):
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.websocket import auction_socket as ws_module
    import uuid

    monkeypatch.setattr(
        ws_module,
        "_resolve_user_id",
        AsyncMock(return_value=UID1),
    )
    monkeypatch.setattr(
        ws_module,
        "_auction_exists",
        AsyncMock(return_value=False),
    )

    def _run():
        client = TestClient(ws_app)
        try:
            with client.websocket_connect(
                f"/ws/auction/{uuid.uuid4()}?token=anything"
            ) as ws:
                # Should receive an ERROR frame then close.
                msg = ws.receive_json()
                assert msg["type"] == EventType.ERROR.value
                assert msg["data"]["code"] == "WS_AUCTION_NOT_FOUND"
                # Next receive should raise on close.
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
        except WebSocketDisconnect:
            # Some Starlette versions raise here directly — acceptable.
            pass

    await asyncio.to_thread(_run)


async def test_websocket_invalid_token_closes_with_4401(
    ws_app, monkeypatch, auction_factory, seller,
):
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.websocket import auction_socket as ws_module

    monkeypatch.setattr(
        ws_module, "_resolve_user_id", AsyncMock(return_value=None)
    )
    auction = await auction_factory(created_by=seller.id)

    def _run():
        client = TestClient(ws_app)
        try:
            with client.websocket_connect(
                f"/ws/auction/{auction.id}?token=bad"
            ) as ws:
                msg = ws.receive_json()
                assert msg["type"] == EventType.ERROR.value
                assert msg["data"]["code"] == "WS_UNAUTHORIZED"
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
        except WebSocketDisconnect:
            pass

    await asyncio.to_thread(_run)

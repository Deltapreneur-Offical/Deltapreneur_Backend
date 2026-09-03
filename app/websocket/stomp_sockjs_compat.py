"""SockJS + STOMP compatibility bridge for legacy frontend clients.

This keeps existing frontend hooks working without changing client code:
- SockJS endpoint base: /ws
- STOMP destinations: /topic/auction/{id}, /topic/community-auction/{id}, …
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, Set

from fastapi import APIRouter, Response, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SockJS/STOMP Compatibility"])


@dataclass(eq=False)
class StompSession:
    websocket: WebSocket
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    subscriptions: Set[str] = field(default_factory=set)

    def __hash__(self) -> int:
        return hash(self.session_id)

    async def send_frame(
        self,
        command: str,
        headers: Dict[str, str] | None = None,
        body: str = "",
    ) -> None:
        hdr = headers or {}
        header_blob = "".join(f"{k}:{v}\n" for k, v in hdr.items())
        frame = f"{command}\n{header_blob}\n{body}\x00"
        await self.websocket.send_text(frame)

    async def send_message(self, destination: str, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":"))
        await self.send_frame(
            "MESSAGE",
            headers={
                "destination": destination,
                "content-type": "application/json",
                "subscription": destination,
                "message-id": uuid.uuid4().hex,
            },
            body=body,
        )


class StompHub:
    def __init__(self) -> None:
        self._subscriptions: Dict[str, Set[StompSession]] = defaultdict(set)
        self._sessions: Dict[str, StompSession] = {}

    def register(self, session: StompSession) -> None:
        self._sessions[session.session_id] = session

    def unregister(self, session: StompSession) -> None:
        self._sessions.pop(session.session_id, None)
        for destination in list(session.subscriptions):
            bucket = self._subscriptions.get(destination)
            if not bucket:
                continue
            bucket.discard(session)
            if not bucket:
                self._subscriptions.pop(destination, None)

    def subscribe(self, session: StompSession, destination: str) -> None:
        session.subscriptions.add(destination)
        self._subscriptions[destination].add(session)

    async def broadcast(self, destination: str, payload: dict) -> int:
        sessions = list(self._subscriptions.get(destination, set()))
        delivered = 0
        dead: list[StompSession] = []
        for session in sessions:
            try:
                await session.send_message(destination, payload)
                delivered += 1
            except Exception:
                dead.append(session)
        for session in dead:
            self.unregister(session)
        return delivered

    async def broadcast_many(self, destinations: Iterable[str], payload: dict) -> int:
        total = 0
        for destination in destinations:
            total += await self.broadcast(destination, payload)
        return total


stomp_hub = StompHub()


def _parse_stomp_frames(raw: str) -> list[tuple[str, Dict[str, str], str]]:
    frames: list[tuple[str, Dict[str, str], str]] = []
    for chunk in raw.split("\x00"):
        text = chunk.strip("\n\r")
        if not text:
            continue
        lines = text.split("\n")
        command = lines[0].strip().upper()
        headers: Dict[str, str] = {}
        i = 1
        while i < len(lines) and lines[i].strip() != "":
            line = lines[i]
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
            i += 1
        body = "\n".join(lines[i + 1 :]) if i < len(lines) else ""
        frames.append((command, headers, body))
    return frames


@router.get("/ws/info")
async def sockjs_info() -> dict:
    # Minimal SockJS info endpoint required by sockjs-client handshake.
    return {
        "websocket": True,
        "origins": ["*:*"],
        "cookie_needed": False,
        "entropy": uuid.uuid4().int & 0x7FFFFFFF,
    }


@router.options("/ws/info")
async def sockjs_info_options() -> Response:
    response = Response(status_code=204)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "OPTIONS, GET"
    response.headers["Access-Control-Allow-Headers"] = "content-type, authorization"
    return response


@router.websocket("/ws/{server_id}/{session_id}/websocket")
async def sockjs_ws(server_id: str, session_id: str, websocket: WebSocket) -> None:
    _ = (server_id, session_id)
    await websocket.accept()
    session = StompSession(websocket=websocket)
    stomp_hub.register(session)
    try:
        while True:
            raw = await websocket.receive_text()
            for command, headers, _body in _parse_stomp_frames(raw):
                if command == "CONNECT":
                    await session.send_frame(
                        "CONNECTED",
                        headers={"version": headers.get("accept-version", "1.2")},
                    )
                elif command == "SUBSCRIBE":
                    destination = headers.get("destination", "")
                    if destination:
                        stomp_hub.subscribe(session, destination)
                elif command == "DISCONNECT":
                    await websocket.close(code=1000)
                    return
                elif command == "PING":
                    await session.send_frame("PONG")
    except WebSocketDisconnect:
        pass
    finally:
        stomp_hub.unregister(session)


def _destinations_for_room(auction_room: str) -> list[str]:
    # Room keys: UUID (domain), community_auction_{id},
    # community_profile_{communityId}, software_auction_{id}
    if auction_room.startswith("community_profile_"):
        community_id = auction_room.replace("community_profile_", "", 1)
        return [f"/topic/creator-profile/{community_id}"]
    if auction_room.startswith("software_auction_"):
        auction_id = auction_room.replace("software_auction_", "", 1)
        return [f"/topic/software-auction/{auction_id}"]
    if auction_room.startswith("community_auction_"):
        auction_id = auction_room.replace("community_auction_", "", 1)
        return [f"/topic/community-auction/{auction_id}"]
    return [f"/topic/auction/{auction_room}"]


async def broadcast_room_compat(auction_room: str, payload: dict) -> int:
    return await stomp_hub.broadcast_many(_destinations_for_room(auction_room), payload)

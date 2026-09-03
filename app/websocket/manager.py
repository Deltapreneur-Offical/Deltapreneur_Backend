from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Union

from fastapi import WebSocket

from app.websocket.connection import WebSocketConnection
from app.websocket.stomp_sockjs_compat import broadcast_room_compat


logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    WebSocket connection manager for auction rooms and/or notification sockets.

    Auction connections are indexed by room (`_rooms`) and by user (`_user_index`)
    so room broadcasts and personal notifications (e.g. USER_OUTBID) can target the
    same live sockets.
    """

    def __init__(self, *, personal_notifications_only: bool = False) -> None:
        self._personal_notifications_only = personal_notifications_only

        self._rooms: Dict[str, set[WebSocketConnection]] = defaultdict(set)

        self._user_index: Dict[uuid.UUID, set[WebSocketConnection]] = defaultdict(
            set
        )

        self._user_connections: Dict[str, List[WebSocket]] = defaultdict(list)

        self.active_connections: Set[Union[WebSocketConnection, WebSocket]] = set()

        self._lock = asyncio.Lock()

    def _normalize_user_id(self, user_id: uuid.UUID | str) -> str:
        return str(user_id)

    def _user_key(self, user_id: uuid.UUID | str) -> uuid.UUID:
        if isinstance(user_id, uuid.UUID):
            return user_id
        return uuid.UUID(str(user_id))

    def _add_to_user_index(self, connection: WebSocketConnection) -> None:
        if connection.user_id is None:
            return
        key = self._user_key(connection.user_id)
        self._user_index[key].add(connection)

    def _remove_from_user_index(self, connection: WebSocketConnection) -> None:
        if connection.user_id is None:
            return
        key = self._user_key(connection.user_id)
        bucket = self._user_index.get(key)
        if not bucket:
            return
        bucket.discard(connection)
        if not bucket:
            self._user_index.pop(key, None)

    # ------------------------------------------------------------------ #
    # Auction room connections                                            #
    # ------------------------------------------------------------------ #

    async def connect(self, connection: WebSocketConnection) -> None:
        async with self._lock:
            self._rooms[connection.auction_id].add(connection)
            self._add_to_user_index(connection)
            self.active_connections.add(connection)

        logger.info(
            "Auction websocket connected auction=%s user=%s",
            connection.auction_id,
            connection.user_id,
        )

    async def disconnect(self, connection: WebSocketConnection) -> None:
        async with self._lock:
            room = self._rooms.get(connection.auction_id)
            if room:
                room.discard(connection)
                if not room:
                    self._rooms.pop(connection.auction_id, None)

            self._remove_from_user_index(connection)
            self.active_connections.discard(connection)

        logger.info(
            "Auction websocket disconnected auction=%s user=%s",
            connection.auction_id,
            connection.user_id,
        )

    async def join_room(
        self,
        connection: WebSocketConnection,
        auction_id: str,
    ) -> None:
        if connection.auction_id == auction_id:
            return

        async with self._lock:
            old_room = self._rooms.get(connection.auction_id)
            if old_room:
                old_room.discard(connection)
                if not old_room:
                    self._rooms.pop(connection.auction_id, None)

            connection.auction_id = auction_id
            self._rooms[auction_id].add(connection)

    async def leave_room(self, connection: WebSocketConnection) -> None:
        async with self._lock:
            room = self._rooms.get(connection.auction_id)
            if room:
                room.discard(connection)
                if not room:
                    self._rooms.pop(connection.auction_id, None)

    def room_size(self, auction_id: str) -> int:
        return len(self._rooms.get(auction_id, set()))

    async def broadcast_to_auction(
        self,
        auction_id: str,
        payload: dict[str, Any],
        *,
        exclude_user_ids: Optional[Iterable[uuid.UUID]] = None,
    ) -> int:
        async with self._lock:
            connections = list(self._rooms.get(auction_id, set()))

        if not connections:
            return 0

        exclude_set = set(exclude_user_ids or [])
        delivered = 0
        dead_connections: list[WebSocketConnection] = []

        for connection in connections:
            if connection.user_id and connection.user_id in exclude_set:
                continue
            try:
                await connection.send_json(payload)
                delivered += 1
            except Exception:
                logger.exception("Auction websocket send failed")
                dead_connections.append(connection)

        for connection in dead_connections:
            await self.disconnect(connection)
            await connection.close(code=1011)

        # Backward compatibility path for frontend SockJS/STOMP subscriptions.
        # This is best-effort and must not break native websocket flow.
        try:
            await broadcast_room_compat(auction_id, payload)
        except Exception:
            logger.exception("SockJS/STOMP compat broadcast failed room=%s", auction_id)

        return delivered

    # ------------------------------------------------------------------ #
    # Dedicated notification sockets (/ws/notifications/{user_id})        #
    # ------------------------------------------------------------------ #

    async def connect_user(
        self,
        user_id: uuid.UUID | str,
        websocket: WebSocket,
        *,
        already_accepted: bool = False,
    ) -> None:
        normalized_user_id = self._normalize_user_id(user_id)

        if not already_accepted:
            await websocket.accept()

        async with self._lock:
            self._user_connections[normalized_user_id].append(websocket)
            self.active_connections.add(websocket)

        logger.info("Personal websocket connected user=%s", normalized_user_id)

    def disconnect_user(
        self,
        user_id: uuid.UUID | str,
        websocket: WebSocket,
    ) -> None:
        normalized_user_id = self._normalize_user_id(user_id)
        connections = self._user_connections.get(normalized_user_id)

        if not connections:
            return

        if websocket in connections:
            connections.remove(websocket)

        if not connections:
            self._user_connections.pop(normalized_user_id, None)

        self.active_connections.discard(websocket)

        logger.info("Personal websocket disconnected user=%s", normalized_user_id)

    async def send_personal_notification(
        self,
        user_id: uuid.UUID | str,
        payload: dict[str, Any],
    ) -> int:
        """
        Deliver to notification sockets and all auction-room sockets for this user.
        """
        normalized_user_id = self._normalize_user_id(user_id)
        user_key = self._user_key(user_id)

        async with self._lock:
            notification_sockets = list(
                self._user_connections.get(normalized_user_id, [])
            )
            auction_connections = list(
                self._user_index.get(user_key, set())
            )

        delivered = 0
        dead_notification_sockets: List[WebSocket] = []
        dead_auction_connections: list[WebSocketConnection] = []

        for websocket in notification_sockets:
            try:
                await websocket.send_json(payload)
                delivered += 1
            except Exception:
                logger.exception(
                    "Personal websocket send failed user=%s",
                    normalized_user_id,
                )
                dead_notification_sockets.append(websocket)

        for connection in auction_connections:
            try:
                await connection.send_json(payload)
                delivered += 1
            except Exception:
                logger.exception(
                    "Auction personal notification send failed user=%s",
                    normalized_user_id,
                )
                dead_auction_connections.append(connection)

        for websocket in dead_notification_sockets:
            self.disconnect_user(
                user_id=normalized_user_id,
                websocket=websocket,
            )

        for connection in dead_auction_connections:
            await self.disconnect(connection)
            await connection.close(code=1011)

        return delivered

    # ------------------------------------------------------------------ #
    # Monitoring                                                          #
    # ------------------------------------------------------------------ #

    def total_connections(self) -> int:
        if self._personal_notifications_only:
            return sum(
                len(connections) for connections in self._user_connections.values()
            )
        return sum(len(connections) for connections in self._rooms.values())

    def active_users(self) -> list[str]:
        return list(self._user_connections.keys())

    def active_auctions(self) -> list[str]:
        return list(self._rooms.keys())

    def active_keys(self) -> list[str]:
        if self._personal_notifications_only:
            return self.active_users()
        return self.active_auctions()


# ---------------------------------------------------------------------- #
# Singleton instances                                                    #
# ---------------------------------------------------------------------- #

connection_manager = ConnectionManager()
community_auction_connection_manager = connection_manager
notification_connection_manager = ConnectionManager(
    personal_notifications_only=True
)


async def broadcast_to_auction(
    auction_id: str,
    payload: dict[str, Any],
    *,
    exclude_user_ids: Optional[Iterable[uuid.UUID]] = None,
) -> int:
    return await connection_manager.broadcast_to_auction(
        auction_id=auction_id,
        payload=payload,
        exclude_user_ids=exclude_user_ids,
    )


async def send_personal_notification(
    user_id: uuid.UUID | str,
    payload: dict[str, Any],
) -> int:
    return await connection_manager.send_personal_notification(
        user_id=user_id,
        payload=payload,
    )

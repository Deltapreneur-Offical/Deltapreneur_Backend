"""
FastAPI WebSocket endpoint for live auction rooms.

URL: /ws/auction/{auction_id}?token=<JWT>

Protocol (JSON messages, line-delimited over the socket):

    client -> server
        {"type": "PING"}         heartbeat (server replies PONG)
        {"type": "PONG"}         response to a server-initiated PING
        anything else            ignored (logged at debug)

    server -> client
        {"type": "CONNECTED",  ...}     on accept
        {"type": "BID_PLACED", ...}     room broadcast (from BidService)
        {"type": "AUCTION_ENDED" / "AUCTION_UNSOLD" / "AUCTION_EXTENDED", ...}
        {"type": "USER_OUTBID", ...}    personal notification
        {"type": "PING", ...}           periodic heartbeat
        {"type": "PONG", ...}           reply to client PING
        {"type": "ERROR", ...}          on protocol / auth failure (then close)

Auth model:
- A short-lived JWT MUST be supplied via the `token` query parameter (browsers
  cannot set Authorization headers on WebSocket handshakes).
- Anonymous (read-only) connections are not allowed at the moment; pass a
  valid access token issued by the existing auth controller.

Close codes used:
    4401  invalid / missing token
    4404  auction not found
    1000  normal closure
    1011  internal error
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token_payload
from app.repository.auction_repository import AuctionRepository
from app.websocket.connection import WebSocketConnection
from app.websocket.events import build_connected, build_error, build_pong
from app.websocket.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


# Heartbeat configuration.
_RECV_TIMEOUT_SECONDS = 60   # close if no client frame in this window
_PING_INTERVAL_SECONDS = 25  # server-initiated keepalive frequency


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


async def _resolve_user_id(token: str) -> Optional[uuid.UUID]:
    """
    Decode `token` and return the bound user's UUID, or None on failure.

    Opens its own short-lived AsyncSession — the WS endpoint cannot rely on
    FastAPI's request-scoped DI because that would tie the DB session to the
    full WebSocket lifetime.
    """
    try:
        payload = decode_access_token_payload(token)
    except Exception:  # noqa: BLE001
        return None

    email = payload.get("sub")
    if not email:
        return None

    try:
        from sqlalchemy import select

        from app.entity.user.app_user import AppUser

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AppUser.id).where(
                    AppUser.email == email,
                    AppUser.active.is_(True),
                    AppUser.is_deleted.is_(False),
                )
            )
            row = result.first()
            if row is None:
                return None
            # AppUser.id is a UUID column; row[0] may already be uuid.UUID
            # depending on the asyncpg dialect — normalise defensively.
            val = row[0]
            return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))
    except Exception:  # noqa: BLE001
        logger.exception("ws.auth.user_lookup_failed")
        return None


async def _auction_exists(auction_id: uuid.UUID) -> bool:
    try:
        async with AsyncSessionLocal() as session:
            repo = AuctionRepository(session)
            return await repo.get_auction_by_id(auction_id) is not None
    except Exception:  # noqa: BLE001
        logger.exception("ws.auction.lookup_failed id=%s", auction_id)
        return False


# --------------------------------------------------------------------------- #
# Endpoint                                                                    #
# --------------------------------------------------------------------------- #


@router.websocket("/ws/auction/{auction_id}")
async def auction_socket(
    websocket: WebSocket,
    auction_id: uuid.UUID,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """Subscribe to realtime events for a single auction room."""

    # Accept first; we can then send a structured ERROR frame on failure
    # before closing — much friendlier to clients than a raw 4xx handshake.
    await websocket.accept()

    user_id = await _resolve_user_id(token)
    if user_id is None:
        await websocket.send_json(build_error("Invalid or expired token.", code="WS_UNAUTHORIZED"))
        await websocket.close(code=4401)
        return

    if not await _auction_exists(auction_id):
        await websocket.send_json(build_error("Auction not found.", code="WS_AUCTION_NOT_FOUND"))
        await websocket.close(code=4404)
        return

    connection = WebSocketConnection(
        websocket=websocket,
        auction_id=str(auction_id),
        user_id=user_id,
    )
    await connection_manager.connect(connection)

    # Greet the client.
    try:
        await connection.send_json(
            build_connected(
                auction_id=auction_id,
                user_id=user_id,
                connection_id=connection.id,
            )
        )
    except Exception:  # noqa: BLE001
        await connection_manager.disconnect(connection)
        return

    # Run receive loop and heartbeat in parallel; first to complete wins.
    heartbeat_task = asyncio.create_task(_heartbeat_loop(connection))
    receive_task = asyncio.create_task(_receive_loop(connection))

    try:
        done, pending = await asyncio.wait(
            {heartbeat_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # Surface any unexpected exception for logging.
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning(
                    "ws.task.error id=%s err=%r", connection.id, exc
                )
    finally:
        await connection_manager.disconnect(connection)
        await connection.close(code=status.WS_1000_NORMAL_CLOSURE)


# --------------------------------------------------------------------------- #
# Loops                                                                       #
# --------------------------------------------------------------------------- #


async def _receive_loop(connection: WebSocketConnection) -> None:
    """
    Read client frames. Closes if:
    - the client disconnects, OR
    - no frame arrives within _RECV_TIMEOUT_SECONDS (dead peer).
    """
    while True:
        try:
            message = await asyncio.wait_for(
                connection.websocket.receive_json(),
                timeout=_RECV_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.info(
                "ws.recv.timeout id=%s — closing idle socket",
                connection.id,
            )
            return
        except WebSocketDisconnect:
            return
        except Exception:  # noqa: BLE001 — malformed JSON, etc.
            try:
                await connection.send_json(
                    build_error("Malformed message.", code="WS_BAD_FRAME")
                )
            except Exception:  # noqa: BLE001
                return
            continue

        msg_type = (message or {}).get("type")
        if msg_type == "PING":
            try:
                await connection.send_json(build_pong())
            except Exception:  # noqa: BLE001
                return
        elif msg_type == "PONG":
            # Client acknowledged our heartbeat — nothing to do.
            continue
        else:
            logger.debug(
                "ws.recv.unhandled id=%s type=%s", connection.id, msg_type
            )


async def _heartbeat_loop(connection: WebSocketConnection) -> None:
    """Server-initiated PING every _PING_INTERVAL_SECONDS."""
    from app.websocket.events import build_ping
    while True:
        await asyncio.sleep(_PING_INTERVAL_SECONDS)
        try:
            await connection.send_json(build_ping())
        except Exception:  # noqa: BLE001
            logger.debug("ws.heartbeat.failed id=%s", connection.id)
            return

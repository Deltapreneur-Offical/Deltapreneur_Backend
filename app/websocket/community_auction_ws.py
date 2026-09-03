"""
WebSocket endpoint for live community auction rooms.

URL: /ws/community-auction/{auction_id}?token=<JWT>
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import decode_access_token_payload
from app.entity.user.app_user import AppUser
from app.repository.community_auction_repository import CommunityAuctionRepository
from app.websocket.connection import WebSocketConnection
from app.websocket.events import build_connected, build_error, build_pong
from app.websocket.manager import community_auction_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Community Auction WebSocket"])

_RECV_TIMEOUT_SECONDS = 60
_PING_INTERVAL_SECONDS = 25


async def _resolve_user_id(token: str) -> Optional[uuid.UUID]:
    try:
        payload = decode_access_token_payload(token)
    except Exception:  # noqa: BLE001
        return None

    email = payload.get("sub")
    if not email:
        return None

    db = SessionLocal()
    try:
        result = db.execute(
            select(AppUser.id).where(
                AppUser.email == email,
                AppUser.active.is_(True),
                AppUser.is_deleted.is_(False),
            )
        )
        row = result.first()
        if row is None:
            return None
        val = row[0]
        return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))
    except Exception:  # noqa: BLE001
        logger.exception("community_ws.auth.user_lookup_failed")
        return None
    finally:
        db.close()


def _community_auction_exists(auction_id: uuid.UUID) -> bool:
    db = SessionLocal()
    try:
        return (
            CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
            is not None
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "community_ws.auction.lookup_failed id=%s", auction_id
        )
        return False
    finally:
        db.close()


@router.websocket("/ws/community-auction/{auction_id}")
async def community_auction_socket(
    websocket: WebSocket,
    auction_id: uuid.UUID,
    token: str = Query(..., description="JWT access token"),
) -> None:
    await websocket.accept()

    user_id = await _resolve_user_id(token)
    if user_id is None:
        await websocket.send_json(
            build_error("Invalid or expired token.", code="WS_UNAUTHORIZED")
        )
        await websocket.close(code=4401)
        return

    if not _community_auction_exists(auction_id):
        await websocket.send_json(
            build_error(
                "Community auction not found.",
                code="WS_AUCTION_NOT_FOUND",
            )
        )
        await websocket.close(code=4404)
        return

    connection = WebSocketConnection(
        websocket=websocket,
        auction_id=str(auction_id),
        user_id=user_id,
    )
    await community_auction_connection_manager.connect(connection)

    try:
        await connection.send_json(
            build_connected(
                auction_id=auction_id,
                user_id=user_id,
                connection_id=connection.id,
            )
        )
    except Exception:  # noqa: BLE001
        await community_auction_connection_manager.disconnect(connection)
        return

    heartbeat_task = asyncio.create_task(_heartbeat_loop(connection))
    receive_task = asyncio.create_task(_receive_loop(connection))

    try:
        done, pending = await asyncio.wait(
            {heartbeat_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning(
                    "community_ws.task.error id=%s err=%r",
                    connection.id,
                    exc,
                )
    finally:
        await community_auction_connection_manager.disconnect(connection)
        await connection.close(code=status.WS_1000_NORMAL_CLOSURE)


async def _receive_loop(connection: WebSocketConnection) -> None:
    while True:
        try:
            message = await asyncio.wait_for(
                connection.websocket.receive_json(),
                timeout=_RECV_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.info(
                "community_ws.recv.timeout id=%s — closing idle socket",
                connection.id,
            )
            return
        except WebSocketDisconnect:
            return
        except Exception:  # noqa: BLE001
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
            continue
        else:
            logger.debug(
                "community_ws.recv.unhandled id=%s type=%s",
                connection.id,
                msg_type,
            )


async def _heartbeat_loop(connection: WebSocketConnection) -> None:
    from app.websocket.events import build_ping

    while True:
        await asyncio.sleep(_PING_INTERVAL_SECONDS)
        try:
            await connection.send_json(build_ping())
        except Exception:  # noqa: BLE001
            logger.debug("community_ws.heartbeat.failed id=%s", connection.id)
            return

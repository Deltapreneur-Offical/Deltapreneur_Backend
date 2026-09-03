"""
Authenticated WebSocket endpoint for live personal notifications.

URL: /ws/notifications/{user_id}?token=<JWT_ACCESS_TOKEN>
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import (
    access_token_invalidated_by_password_change,
    decode_access_token_payload,
)
from app.entity.user.app_user import AppUser
from app.websocket.manager import notification_connection_manager


logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Notification WebSocket"],
)


async def _resolve_user_id(token: str) -> Optional[uuid.UUID]:
    """
    Resolve the active authenticated user from the JWT token.

    Uses AsyncSessionLocal (same as auction WS) — sync SessionLocal can fail
    independently of REST and leave the socket unaccepted in the browser.
    """
    try:
        payload = decode_access_token_payload(token)
    except Exception:  # noqa: BLE001
        return None

    email = payload.get("sub")
    if not email:
        return None

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AppUser).where(
                    AppUser.email == email,
                    AppUser.active.is_(True),
                    AppUser.is_deleted.is_(False),
                )
            )
            user = result.scalar_one_or_none()
            if user is None:
                return None
            if access_token_invalidated_by_password_change(payload, user):
                return None
            return user.id if isinstance(user.id, uuid.UUID) else uuid.UUID(str(user.id))
    except Exception:  # noqa: BLE001
        logger.exception("notification_ws.auth.user_lookup_failed")
        return None


@router.websocket("/ws/notifications/{user_id}")
async def notification_websocket(
    websocket: WebSocket,
    user_id: uuid.UUID,
    token: str = Query(..., description="JWT access token"),
) -> None:
    # Accept first so auth failures close with a real code (not a browser "failed").
    await websocket.accept()

    authenticated_user_id = await _resolve_user_id(token)

    if authenticated_user_id is None:
        logger.warning("notification_ws.auth.invalid_token requested_user=%s", user_id)
        await websocket.close(code=4401)
        return

    if authenticated_user_id != user_id:
        logger.warning(
            "notification_ws.auth.user_mismatch token_user=%s requested_user=%s",
            authenticated_user_id,
            user_id,
        )
        await websocket.close(code=4403)
        return

    await notification_connection_manager.connect_user(
        user_id=user_id,
        websocket=websocket,
        already_accepted=True,
    )

    logger.info("notification_ws.connected user=%s", user_id)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("notification_ws.disconnected user=%s", user_id)

    finally:
        notification_connection_manager.disconnect_user(
            user_id=user_id,
            websocket=websocket,
        )

"""
WebSocketConnection — value object representing one live client socket.

Holds the underlying Starlette WebSocket plus the room / user identity it
belongs to. Equality and hashing are based on a stable per-connection UUID,
so the same Connection can be stored in multiple set-based indexes
(room index, per-user index) without collisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket


@dataclass(eq=False)
class WebSocketConnection:
    """A single tracked WebSocket session."""

    websocket: WebSocket
    auction_id: str
    user_id: Optional[uuid.UUID] = None   # UUID — matches AppUser.id
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    connected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ----- Identity / hashing ------------------------------------------------

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(self.id)

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        return isinstance(other, WebSocketConnection) and self.id == other.id

    # ----- IO helpers --------------------------------------------------------

    async def send_json(self, payload: dict) -> None:
        """Send a JSON payload. Raises on transport error."""
        await self.websocket.send_json(payload)

    async def close(self, code: int = 1000) -> None:
        """Close the underlying socket. Idempotent w.r.t. caller exceptions."""
        try:
            await self.websocket.close(code=code)
        except Exception:  # noqa: BLE001
            # The socket may already be closed by the peer or runtime.
            pass

    def to_dict(self) -> dict:
        """Debug / introspection helper."""
        return {
            "id": str(self.id),
            "auction_id": self.auction_id,
            "user_id": self.user_id,
            "connected_at": self.connected_at.isoformat(),
        }

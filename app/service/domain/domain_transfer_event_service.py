"""Append-only audit log for transfer transactions."""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.domain.domain_transfer_event_entity import DomainTransferEvent
from app.repository.domain_transfer_event_repository import DomainTransferEventRepository
from app.utils.transfer_enums import TransferEventType


class DomainTransferEventService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = DomainTransferEventRepository(session)

    async def log(
        self,
        transaction_id: uuid.UUID,
        event_type: TransferEventType,
        *,
        actor_user_id: Optional[uuid.UUID] = None,
        actor_role: str = "SYSTEM",
        payload: Optional[dict[str, Any]] = None,
    ) -> DomainTransferEvent:
        safe_payload = dict(payload or {})
        if "authCode" in safe_payload:
            safe_payload["authCode"] = "[REDACTED]"
        event = DomainTransferEvent(
            transaction_id=transaction_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload_json=json.dumps(safe_payload, default=str) if safe_payload else None,
        )
        return await self._repo.create(event)

    async def list_timeline(self, transaction_id: uuid.UUID) -> list[dict[str, Any]]:
        events = await self._repo.list_by_transaction(transaction_id)
        return [
            {
                "id": str(e.id),
                "eventType": e.event_type.value,
                "actorUserId": str(e.actor_user_id) if e.actor_user_id else None,
                "actorRole": e.actor_role,
                "payload": json.loads(e.payload_json) if e.payload_json else None,
                "createdAt": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]

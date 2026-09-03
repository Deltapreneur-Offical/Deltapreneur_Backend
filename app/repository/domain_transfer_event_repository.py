"""Transfer audit event repository."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.domain.domain_transfer_event_entity import DomainTransferEvent


class DomainTransferEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: DomainTransferEvent) -> DomainTransferEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_by_transaction(self, transaction_id: uuid.UUID) -> Sequence[DomainTransferEvent]:
        stmt = (
            select(DomainTransferEvent)
            .where(DomainTransferEvent.transaction_id == transaction_id)
            .order_by(DomainTransferEvent.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

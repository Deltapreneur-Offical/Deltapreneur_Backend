"""CoBrother request data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.utils.marketplace_enums import CoBrotherRequestStatus


class CoBrotherRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: CoBrotherRequest) -> CoBrotherRequest:
        self._session.add(request)
        await self._session.flush()
        await self._session.refresh(request)
        return request

    async def save(self, request: CoBrotherRequest) -> CoBrotherRequest:
        await self._session.flush()
        await self._session.refresh(request)
        return request

    async def get_by_id(self, request_id: uuid.UUID) -> Optional[CoBrotherRequest]:
        stmt = select(CoBrotherRequest).where(CoBrotherRequest.id == request_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_payment_pending_for_lister(
        self,
        lister_id: uuid.UUID,
    ) -> Sequence[CoBrotherRequest]:
        stmt = (
            select(CoBrotherRequest)
            .where(
                CoBrotherRequest.lister_id == lister_id,
                CoBrotherRequest.status == CoBrotherRequestStatus.PAYMENT_PENDING,
            )
            .order_by(CoBrotherRequest.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_assignee(
        self,
        cobrother_id: uuid.UUID,
        *,
        status: Optional[CoBrotherRequestStatus] = None,
    ) -> Sequence[CoBrotherRequest]:
        stmt = (
            select(CoBrotherRequest)
            .where(CoBrotherRequest.assigned_cobrother_id == cobrother_id)
            .order_by(CoBrotherRequest.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(CoBrotherRequest.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_pending_for_entity(
        self,
        entity_id: uuid.UUID,
    ) -> Sequence[CoBrotherRequest]:
        stmt = select(CoBrotherRequest).where(
            CoBrotherRequest.entity_id == entity_id,
            CoBrotherRequest.status == CoBrotherRequestStatus.PENDING,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

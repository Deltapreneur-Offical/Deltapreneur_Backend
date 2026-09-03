"""Operations hire/booking request persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.operations.operations_service_request_entity import OperationsServiceRequest


class OperationsServiceRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _with_user() -> tuple:
        return (selectinload(OperationsServiceRequest.user),)

    async def get_by_id(self, request_id: uuid.UUID) -> OperationsServiceRequest | None:
        stmt = (
            select(OperationsServiceRequest)
            .options(*self._with_user())
            .where(OperationsServiceRequest.id == request_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_pending_for_user_service(
        self,
        *,
        user_id: uuid.UUID,
        operations_service_id: uuid.UUID,
    ) -> OperationsServiceRequest | None:
        stmt = (
            select(OperationsServiceRequest)
            .options(*self._with_user())
            .where(
                OperationsServiceRequest.user_id == user_id,
                OperationsServiceRequest.operations_service_id == operations_service_id,
                OperationsServiceRequest.status == "PENDING",
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_admin(
        self,
        *,
        request_type: str | None = None,
        status: str | None = None,
    ) -> list[OperationsServiceRequest]:
        stmt = (
            select(OperationsServiceRequest)
            .options(*self._with_user())
            .order_by(OperationsServiceRequest.created_at.desc())
        )
        if request_type:
            stmt = stmt.where(OperationsServiceRequest.request_type == request_type)
        if status:
            stmt = stmt.where(OperationsServiceRequest.status == status.upper())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_user(self, user_id: uuid.UUID) -> list[OperationsServiceRequest]:
        stmt = (
            select(OperationsServiceRequest)
            .options(*self._with_user())
            .where(OperationsServiceRequest.user_id == user_id)
            .order_by(OperationsServiceRequest.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, row: OperationsServiceRequest) -> OperationsServiceRequest:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(self, row: OperationsServiceRequest) -> OperationsServiceRequest:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def delete(self, row: OperationsServiceRequest) -> None:
        await self._session.delete(row)
        await self._session.flush()

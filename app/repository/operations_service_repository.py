"""Operations service catalog persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.operations.operations_service_entity import OperationsService


class OperationsServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _alive_filter(self):
        return OperationsService.is_deleted.is_(False)

    async def list_admin(self) -> list[OperationsService]:
        stmt = (
            select(OperationsService)
            .where(self._alive_filter())
            .order_by(
                OperationsService.display_order.asc(),
                OperationsService.name.asc(),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_public(
        self,
        *,
        service_type: str | None = None,
    ) -> list[OperationsService]:
        stmt = (
            select(OperationsService)
            .where(
                self._alive_filter(),
                OperationsService.is_available.is_(True),
            )
            .order_by(
                OperationsService.display_order.asc(),
                OperationsService.name.asc(),
            )
        )
        if service_type:
            stmt = stmt.where(OperationsService.service_type == service_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(
        self,
        service_id: uuid.UUID,
        *,
        public_only: bool = False,
    ) -> OperationsService | None:
        stmt = select(OperationsService).where(
            OperationsService.id == service_id,
            self._alive_filter(),
        )
        if public_only:
            stmt = stmt.where(OperationsService.is_available.is_(True))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_max_display_order(self) -> int:
        stmt = (
            select(OperationsService.display_order)
            .where(self._alive_filter())
            .order_by(OperationsService.display_order.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return int(value or 0)

    async def create(self, row: OperationsService) -> OperationsService:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(self, row: OperationsService) -> OperationsService:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def soft_delete(
        self,
        row: OperationsService,
        *,
        deleted_by: uuid.UUID | None = None,
    ) -> None:
        row.is_deleted = True
        row.deleted_at = datetime.now(timezone.utc)
        row.deleted_by = deleted_by
        await self._session.flush()

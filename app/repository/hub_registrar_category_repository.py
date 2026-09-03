"""Hub Registrar category persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.hub_registrar.hub_registrar_category_entity import HubRegistrarCategory


class HubRegistrarCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _alive_filter(self):
        return HubRegistrarCategory.is_deleted.is_(False)

    async def list_admin(self) -> list[HubRegistrarCategory]:
        stmt = (
            select(HubRegistrarCategory)
            .where(self._alive_filter())
            .order_by(
                HubRegistrarCategory.display_order.asc(),
                HubRegistrarCategory.name.asc(),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_public(self) -> list[HubRegistrarCategory]:
        stmt = (
            select(HubRegistrarCategory)
            .where(
                self._alive_filter(),
                HubRegistrarCategory.is_active.is_(True),
            )
            .order_by(
                HubRegistrarCategory.display_order.asc(),
                HubRegistrarCategory.name.asc(),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(
        self,
        category_id: uuid.UUID,
        *,
        public_only: bool = False,
    ) -> HubRegistrarCategory | None:
        stmt = select(HubRegistrarCategory).where(
            HubRegistrarCategory.id == category_id,
            self._alive_filter(),
        )
        if public_only:
            stmt = stmt.where(HubRegistrarCategory.is_active.is_(True))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> HubRegistrarCategory | None:
        stmt = select(HubRegistrarCategory).where(
            HubRegistrarCategory.slug == slug,
            self._alive_filter(),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_max_display_order(self) -> int:
        stmt = (
            select(HubRegistrarCategory.display_order)
            .where(self._alive_filter())
            .order_by(HubRegistrarCategory.display_order.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return int(value or 0)

    async def create(self, row: HubRegistrarCategory) -> HubRegistrarCategory:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(self, row: HubRegistrarCategory) -> HubRegistrarCategory:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def soft_delete(
        self,
        row: HubRegistrarCategory,
        *,
        deleted_by: uuid.UUID | None = None,
    ) -> None:
        row.is_deleted = True
        row.deleted_at = datetime.now(timezone.utc)
        row.deleted_by = deleted_by
        await self._session.flush()

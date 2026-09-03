"""Software listing data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.cocreation.software_entity import Software


def _alive_software():
    return Software.is_deleted.is_(False)


class SoftwareRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, software: Software) -> Software:
        self._session.add(software)
        await self._session.flush()
        await self._session.refresh(software)
        return software

    async def save(self, software: Software) -> Software:
        await self._session.flush()
        await self._session.refresh(software)
        return software

    async def get_by_id(self, software_id: uuid.UUID) -> Optional[Software]:
        stmt = (
            select(Software)
            .where(Software.id == software_id, _alive_software())
            .options(selectinload(Software.listed_by), selectinload(Software.agreement))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def _public_list_filters(self):
        return (
            _alive_software(),
            Software.taken_down.is_(False),
            Software.status.is_(True),
        )

    async def count_all_active(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Software)
            .where(*self._public_list_filters())
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def list_all_active(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Software]:
        stmt = (
            select(Software)
            .where(*self._public_list_filters())
            .options(selectinload(Software.listed_by))
            .order_by(Software.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.offset(max(0, offset)).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_homepage_featured(
        self,
        *,
        limit: int | None = None,
    ) -> Sequence[Software]:
        stmt = (
            select(Software)
            .where(
                _alive_software(),
                Software.taken_down.is_(False),
                Software.status.is_(True),
                Software.featured.is_(True),
                # Pending admin verification must not appear on the homepage strip.
                Software.verified.is_(True),
            )
            .options(selectinload(Software.listed_by))
            .order_by(Software.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(max(1, limit))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_lister(self, user_id: uuid.UUID) -> Sequence[Software]:
        stmt = (
            select(Software)
            .where(Software.listed_by_user_id == user_id, _alive_software())
            .order_by(Software.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

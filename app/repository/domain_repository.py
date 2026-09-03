"""Async repository for Domain entities (ownership + soft-delete aware)."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.auction.domain_entity import Domain


def _alive_domain() -> object:
    return Domain.is_deleted.is_(False)


class DomainRepository:
    """Data access for `domains` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, domain: Domain) -> Domain:
        self._session.add(domain)
        await self._session.flush()
        await self._session.refresh(domain)
        return domain

    async def get_by_id_alive(self, domain_id: uuid.UUID) -> Optional[Domain]:
        stmt = select(Domain).where(Domain.id == domain_id, _alive_domain())
        r = await self._session.execute(stmt)
        return r.scalar_one_or_none()

    async def get_by_id_for_owner(
        self,
        domain_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> Optional[Domain]:
        stmt = select(Domain).where(
            Domain.id == domain_id,
            Domain.owner_id == owner_id,
            _alive_domain(),
        )
        r = await self._session.execute(stmt)
        return r.scalar_one_or_none()

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Domain)
            .where(Domain.owner_id == owner_id, _alive_domain())
        )
        r = await self._session.execute(stmt)
        return int(r.scalar_one() or 0)

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
    ) -> Sequence[Domain]:
        stmt = (
            select(Domain)
            .where(Domain.owner_id == owner_id, _alive_domain())
            .order_by(Domain.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        r = await self._session.execute(stmt)
        return r.scalars().all()

    async def exists_active_domain_name(
        self,
        domain_name: str,
        *,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> bool:
        stmt = select(Domain.id).where(
            Domain.domain_name == domain_name,
            _alive_domain(),
        )
        if exclude_id is not None:
            stmt = stmt.where(Domain.id != exclude_id)
        stmt = stmt.limit(1)
        r = await self._session.execute(stmt)
        return r.scalar_one_or_none() is not None

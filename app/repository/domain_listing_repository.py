"""Domain marketplace listing data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.cobranding.domain_listing_entity import DomainListing
from app.utils.marketplace_enums import DomainListingStatus, SaleType


def _alive_listing():
    return DomainListing.is_deleted.is_(False)


def _listing_detail_options():
    return (
        selectinload(DomainListing.contact_info),
        selectinload(DomainListing.agreement),
        selectinload(DomainListing.listed_by),
        selectinload(DomainListing.purchased_by),
        selectinload(DomainListing.verified_by),
    )


class DomainListingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, listing: DomainListing) -> DomainListing:
        self._session.add(listing)
        await self._session.flush()
        await self._session.refresh(listing)
        return listing

    async def save(self, listing: DomainListing) -> DomainListing:
        await self._session.flush()
        await self._session.refresh(listing)
        return listing

    async def increment_views(self, listing_id: uuid.UUID) -> None:
        from sqlalchemy import update
        stmt = (
            update(DomainListing)
            .where(DomainListing.id == listing_id)
            .values(views=DomainListing.views + 1)
        )
        await self._session.execute(stmt)

    async def get_by_id(self, listing_id: uuid.UUID) -> Optional[DomainListing]:
        stmt = (
            select(DomainListing)
            .where(DomainListing.id == listing_id, _alive_listing())
            .options(*_listing_detail_options())
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_basic(self, listing_id: uuid.UUID) -> Optional[DomainListing]:
        """Load listing row only — used for mutations that do not need relationships."""
        stmt = select(DomainListing).where(
            DomainListing.id == listing_id,
            _alive_listing(),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, listing_id: uuid.UUID) -> Optional[DomainListing]:
        stmt = (
            select(DomainListing)
            .where(DomainListing.id == listing_id, _alive_listing())
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(self, listing_ids: list[uuid.UUID]) -> Sequence[DomainListing]:
        if not listing_ids:
            return []
        stmt = (
            select(DomainListing)
            .where(DomainListing.id.in_(listing_ids), _alive_listing())
            .options(*_listing_detail_options())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    def _active_marketplace_filters(self):
        # UNDER_REVIEW stays publicly visible (premium acquisition in progress).
        return (
            _alive_listing(),
            DomainListing.taken_down.is_(False),
            DomainListing.status.is_(True),
            DomainListing.domain_status.in_(
                (
                    DomainListingStatus.AVAILABLE,
                    DomainListingStatus.UNDER_REVIEW,
                )
            ),
        )

    async def count_all_active(self) -> int:
        stmt = (
            select(func.count())
            .select_from(DomainListing)
            .where(*self._active_marketplace_filters())
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def list_all_active(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[DomainListing]:
        stmt = (
            select(DomainListing)
            .where(*self._active_marketplace_filters())
            .options(*_listing_detail_options())
            .order_by(
                DomainListing.featured.desc(),
                DomainListing.verified.desc(),
                DomainListing.created_at.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.offset(max(0, offset)).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_homepage_featured(
        self,
        *,
        limit: int | None = None,
    ) -> Sequence[DomainListing]:
        stmt = (
            select(DomainListing)
            .where(
                _alive_listing(),
                DomainListing.taken_down.is_(False),
                DomainListing.status.is_(True),
                DomainListing.featured.is_(True),
                DomainListing.domain_status.in_(
                    (
                        DomainListingStatus.AVAILABLE,
                        DomainListingStatus.UNDER_REVIEW,
                    )
                ),
            )
            .options(*_listing_detail_options())
            .order_by(DomainListing.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(max(1, limit))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def search_active_non_auction(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> Sequence[DomainListing]:
        pattern = f"%{query.strip().lower()}%"
        full_domain = func.lower(DomainListing.domain_name + DomainListing.domain_extension)
        stmt = (
            select(DomainListing)
            .where(
                _alive_listing(),
                DomainListing.taken_down.is_(False),
                DomainListing.status.is_(True),
                DomainListing.domain_status.in_(
                    (
                        DomainListingStatus.AVAILABLE,
                        DomainListingStatus.UNDER_REVIEW,
                    )
                ),
                DomainListing.sale_type != SaleType.AUCTION,
                (
                    func.lower(DomainListing.domain_name).like(pattern)
                    | func.lower(DomainListing.domain_extension).like(pattern)
                    | full_domain.like(pattern)
                ),
            )
            .options(*_listing_detail_options())
            .order_by(DomainListing.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_lister(self, user_id: uuid.UUID) -> Sequence[DomainListing]:
        stmt = (
            select(DomainListing)
            .where(DomainListing.listed_by_user_id == user_id, _alive_listing())
            .options(*_listing_detail_options())
            .order_by(DomainListing.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_buyer(self, user_id: uuid.UUID) -> Sequence[DomainListing]:
        stmt = (
            select(DomainListing)
            .where(DomainListing.purchased_by_user_id == user_id, _alive_listing())
            .options(*_listing_detail_options())
            .order_by(DomainListing.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def exists_name(
        self,
        domain_name: str,
        extension: str,
        *,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> bool:
        stmt = select(func.count()).select_from(DomainListing).where(
            func.lower(DomainListing.domain_name) == domain_name.lower(),
            DomainListing.domain_extension == extension,
            _alive_listing(),
        )
        if exclude_id:
            stmt = stmt.where(DomainListing.id != exclude_id)
        result = await self._session.execute(stmt)
        return (result.scalar() or 0) > 0

    async def find_active_by_name(
        self,
        domain_name: str,
        extension: str,
    ) -> Optional[DomainListing]:
        """Active marketplace listing (not deleted, not taken down)."""
        stmt = (
            select(DomainListing)
            .where(
                func.lower(DomainListing.domain_name) == domain_name.lower(),
                DomainListing.domain_extension == extension,
                _alive_listing(),
                DomainListing.taken_down.is_(False),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

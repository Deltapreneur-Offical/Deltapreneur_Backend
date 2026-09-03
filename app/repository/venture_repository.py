"""Venture data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.coventure.venture_entity import Venture
from app.utils.venture_enums import (
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
)


def _alive_venture():
    return Venture.is_deleted.is_(False)


class VentureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, venture: Venture) -> Venture:
        self._session.add(venture)
        await self._session.flush()
        await self._session.refresh(venture)
        return venture

    async def save(self, venture: Venture) -> Venture:
        await self._session.flush()
        await self._session.refresh(venture)
        return venture

    async def get_by_id(
        self,
        venture_id: uuid.UUID,
        *,
        load_roles: bool = True,
    ) -> Optional[Venture]:
        stmt = select(Venture).where(
            Venture.id == venture_id,
            _alive_venture(),
        )
        if load_roles:
            stmt = stmt.options(
                selectinload(Venture.roles),
                selectinload(Venture.brand_details),
                selectinload(Venture.contact_info),
                selectinload(Venture.agreement),
                selectinload(Venture.listed_by),
                selectinload(Venture.financial_profile),
                selectinload(Venture.documents),
                selectinload(Venture.company_profile),
            )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def _public_list_filters(
        self,
        *,
        listing_mode: VentureListingMode | None = None,
        include_pending: bool = False,
    ):
        """Public marketplace catalog — admin-approved active listings."""
        filters = [
            _alive_venture(),
            Venture.taken_down.is_(False),
            Venture.status.is_(True),
            Venture.venture_listing_status == VentureListingStatus.ACTIVE,
        ]
        if listing_mode is not None:
            filters.append(Venture.listing_mode == listing_mode)
        if not include_pending:
            filters.append(
                Venture.listing_approval_status == VentureListingApprovalStatus.APPROVED
            )
        return tuple(filters)

    async def list_pending_approval(self) -> Sequence[Venture]:
        stmt = (
            select(Venture)
            .where(
                _alive_venture(),
                Venture.listing_approval_status
                == VentureListingApprovalStatus.PENDING_APPROVAL,
            )
            .options(
                selectinload(Venture.roles),
                selectinload(Venture.brand_details),
                selectinload(Venture.listed_by),
            )
            .order_by(Venture.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    def _homepage_featured_filters(
        self,
        *,
        listing_mode: VentureListingMode | None = None,
    ):
        """Admin-pinned homepage rows — no approval gate."""
        filters = [
            _alive_venture(),
            Venture.taken_down.is_(False),
            Venture.status.is_(True),
            Venture.featured.is_(True),
        ]
        if listing_mode is not None:
            filters.append(Venture.listing_mode == listing_mode)
        return tuple(filters)

    async def list_homepage_featured(
        self,
        *,
        limit: int | None = None,
        listing_mode: VentureListingMode | None = None,
    ) -> Sequence[Venture]:
        stmt = (
            select(Venture)
            .where(*self._homepage_featured_filters(listing_mode=listing_mode))
            .options(
                selectinload(Venture.roles),
                selectinload(Venture.brand_details),
                selectinload(Venture.listed_by),
            )
            .order_by(Venture.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(max(1, limit))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_public(
        self,
        *,
        listing_mode: VentureListingMode | None = None,
        include_pending: bool = False,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Venture)
            .where(*self._public_list_filters(listing_mode=listing_mode, include_pending=include_pending))
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
        listing_mode: VentureListingMode | None = None,
        include_pending: bool = False,
    ) -> Sequence[Venture]:
        stmt = (
            select(Venture)
            .where(*self._public_list_filters(listing_mode=listing_mode, include_pending=include_pending))
            .options(
                selectinload(Venture.roles),
                selectinload(Venture.brand_details),
                selectinload(Venture.listed_by),
            )
            .order_by(Venture.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.offset(max(0, offset)).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_buyer(self, user_id: uuid.UUID) -> Sequence[Venture]:
        stmt = (
            select(Venture)
            .where(
                Venture.purchased_by_user_id == user_id,
                _alive_venture(),
            )
            .options(
                selectinload(Venture.roles),
                selectinload(Venture.brand_details),
                selectinload(Venture.contact_info),
                selectinload(Venture.agreement),
                selectinload(Venture.listed_by),
            )
            .order_by(Venture.updated_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_lister(self, user_id: uuid.UUID) -> Sequence[Venture]:
        stmt = (
            select(Venture)
            .where(
                Venture.listed_by_user_id == user_id,
                _alive_venture(),
            )
            .options(
                selectinload(Venture.roles),
                selectinload(Venture.brand_details),
                selectinload(Venture.contact_info),
                selectinload(Venture.agreement),
                selectinload(Venture.listed_by),
            )
            .order_by(Venture.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def exists(self, venture_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(Venture).where(
            Venture.id == venture_id,
            _alive_venture(),
        )
        result = await self._session.execute(stmt)
        return (result.scalar() or 0) > 0

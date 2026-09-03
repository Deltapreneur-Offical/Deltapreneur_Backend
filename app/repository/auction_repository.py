"""
Async repository for the Auction entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.auction.auction_entity import Auction
from app.entity.auction.domain_entity import Domain
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.utils.enums import AuctionStatus
from app.utils.marketplace_enums import (
    DomainListingVerificationStatus,
    SaleType,
)


def _alive_auction() -> Any:
    return Auction.is_deleted.is_(False)


def _public_auction_listing_visibility() -> Any:
    """Hide auction-domain listings until admin verification_status is VERIFIED."""
    return or_(
        DomainListing.id.is_(None),
        DomainListing.sale_type != SaleType.AUCTION,
        DomainListing.verification_status == DomainListingVerificationStatus.VERIFIED,
    )


_BLOCKING_STATUSES = (
    AuctionStatus.DRAFT,
    AuctionStatus.ACTIVE,
    AuctionStatus.EXTENDED,
)


class AuctionRepository:
    """Data access for `auctions` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_auction(self, auction: Auction) -> Auction:
        self._session.add(auction)
        await self._session.flush()
        await self._session.refresh(auction)
        return auction

    async def get_auction_by_id(
        self,
        auction_id: uuid.UUID,
        *,
        load_bids: bool = False,
    ) -> Optional[Auction]:
        stmt = select(Auction).where(Auction.id == auction_id, _alive_auction())
        if load_bids:
            stmt = stmt.options(
                selectinload(Auction.bids),
                selectinload(Auction.domain).selectinload(Domain.owner),
                selectinload(Auction.current_winner),
            )
        else:
            stmt = stmt.options(
                selectinload(Auction.domain).selectinload(Domain.owner),
            )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_auction_by_domain(
        self,
        domain_id: uuid.UUID,
        *,
        active_only: bool = False,
    ) -> Optional[Auction]:
        stmt = (
            select(Auction)
            .where(
                Auction.domain_id == domain_id,
                _alive_auction(),
            )
            .order_by(Auction.created_at.desc())
        )
        if active_only:
            stmt = stmt.where(
                Auction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
                )
            )
        result = await self._session.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def get_blocking_auction_by_domain(
        self,
        domain_id: uuid.UUID,
    ) -> Optional[Auction]:
        stmt = (
            select(Auction)
            .where(
                Auction.domain_id == domain_id,
                Auction.status.in_(_BLOCKING_STATUSES),
                _alive_auction(),
            )
            .order_by(Auction.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_auctions(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Auction]:
        stmt = (
            select(Auction)
            .where(
                Auction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
                ),
                _alive_auction(),
            )
            .order_by(Auction.end_time.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_created_by(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 200,
    ) -> Sequence[Auction]:
        """Auctions listed by this user (seller tracking). Read-only select."""
        stmt = (
            select(Auction)
            .where(Auction.created_by == user_id, _alive_auction())
            .options(selectinload(Auction.domain).selectinload(Domain.owner))
            .order_by(Auction.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_ids(
        self,
        auction_ids: Sequence[uuid.UUID],
    ) -> Sequence[Auction]:
        if not auction_ids:
            return []
        stmt = (
            select(Auction)
            .where(Auction.id.in_(list(auction_ids)), _alive_auction())
            .options(selectinload(Auction.domain).selectinload(Domain.owner))
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_active_auctions_with_details(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Auction]:
        stmt = (
            select(Auction)
            .outerjoin(
                DomainListing,
                DomainListing.id == Auction.domain_id,
            )
            .where(
                Auction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
                ),
                _alive_auction(),
                _public_auction_listing_visibility(),
            )
            .options(
                selectinload(Auction.domain).selectinload(Domain.owner),
            )
            .order_by(Auction.end_time.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.unique().scalars().all()

    async def search_active_auctions_with_details(
        self,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Auction]:
        pattern = f"%{query.strip().lower()}%"
        stmt = (
            select(Auction)
            .outerjoin(Domain, Auction.domain_id == Domain.id)
            .outerjoin(
                DomainListing,
                DomainListing.id == Auction.domain_id,
            )
            .where(
                Auction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
                ),
                _alive_auction(),
                _public_auction_listing_visibility(),
                func.lower(Domain.domain_name).like(pattern),
            )
            .options(
                selectinload(Auction.domain).selectinload(Domain.owner),
            )
            .order_by(Auction.end_time.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.unique().scalars().all()

    async def list_all_auctions(
        self,
        *,
        status: Optional[AuctionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Auction]:
        stmt = select(Auction).where(_alive_auction()).order_by(
            Auction.created_at.desc()
        )
        if status is not None:
            stmt = stmt.where(Auction.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_all_with_details(
        self,
        *,
        status: Optional[AuctionStatus] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> Sequence[Auction]:
        """Admin listing with domain, owner, bids, and winner loaded."""
        stmt = (
            select(Auction)
            .where(_alive_auction())
            .options(
                selectinload(Auction.domain).selectinload(Domain.owner),
                selectinload(Auction.bids),
                selectinload(Auction.current_winner),
            )
            .order_by(Auction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(Auction.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_active_auctions(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Auction)
            .outerjoin(
                DomainListing,
                DomainListing.id == Auction.domain_id,
            )
            .where(
                Auction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
                ),
                _alive_auction(),
                _public_auction_listing_visibility(),
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def count_all_auctions(
        self,
        *,
        status: Optional[AuctionStatus] = None,
    ) -> int:
        stmt = select(func.count()).select_from(Auction).where(_alive_auction())
        if status is not None:
            stmt = stmt.where(Auction.status == status)
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_expired_auctions(
        self,
        *,
        now: Optional[datetime] = None,
        limit: int = 100,
    ) -> Sequence[Auction]:
        now = now or datetime.now(timezone.utc)
        stmt = (
            select(Auction)
            .where(
                Auction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
                ),
                Auction.end_time <= now,
                _alive_auction(),
            )
            .order_by(Auction.end_time.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def update_auction(
        self,
        auction_id: uuid.UUID,
        **fields: Any,
    ) -> Optional[Auction]:
        if not fields:
            return await self.get_auction_by_id(auction_id)

        stmt = (
            update(Auction)
            .where(
                Auction.id == auction_id,
                _alive_auction(),
            )
            .values(**fields)
            .returning(Auction)
            .execution_options(synchronize_session="fetch")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one_or_none()

    async def close_auction(
        self,
        auction_id: uuid.UUID,
        *,
        final_status: AuctionStatus,
    ) -> Optional[Auction]:
        return await self.update_auction(auction_id, status=final_status)

    async def retire_all_for_domain(
        self,
        domain_id: uuid.UUID,
        *,
        deleted_by: uuid.UUID,
    ) -> int:
        """Cancel and soft-delete all auctions tied to a marketplace listing/domain."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(Auction)
            .where(
                Auction.domain_id == domain_id,
                _alive_auction(),
            )
            .values(
                status=AuctionStatus.CANCELLED,
                is_deleted=True,
                deleted_at=now,
                deleted_by=deleted_by,
                updated_at=now,
            )
            .execution_options(synchronize_session="fetch")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

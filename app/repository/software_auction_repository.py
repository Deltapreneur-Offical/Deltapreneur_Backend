"""Software auction data access."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.cocreation.software_auction_bid import SoftwareAuctionBid
from app.entity.cocreation.software_entity import Software
from app.utils.cocreation_enums import SoftwareAuctionApprovalStatus
from app.utils.enums import AuctionStatus


def _with_software() -> list:
    return [
        selectinload(SoftwareAuction.software).selectinload(Software.listed_by),
        selectinload(SoftwareAuction.taken_down_by),
    ]


class SoftwareAuctionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, auction: SoftwareAuction) -> SoftwareAuction:
        self._session.add(auction)
        await self._session.flush()
        await self._session.refresh(auction)
        return auction

    async def save(self, auction: SoftwareAuction) -> SoftwareAuction:
        await self._session.flush()
        await self._session.refresh(auction)
        return auction

    async def get_by_id(
        self,
        auction_id: uuid.UUID,
        *,
        load_bids: bool = False,
    ) -> Optional[SoftwareAuction]:
        stmt = select(SoftwareAuction).where(SoftwareAuction.id == auction_id)
        opts = _with_software()
        if load_bids:
            opts.append(selectinload(SoftwareAuction.bids))
        stmt = stmt.options(*opts)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_software_id(self, software_id: uuid.UUID) -> Optional[SoftwareAuction]:
        stmt = (
            select(SoftwareAuction)
            .where(SoftwareAuction.software_id == software_id)
            .options(*_with_software())
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def map_by_software_ids(
        self,
        software_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, SoftwareAuction]:
        if not software_ids:
            return {}
        stmt = select(SoftwareAuction).where(
            SoftwareAuction.software_id.in_(list(software_ids)),
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return {row.software_id: row for row in rows}

    async def delete_by_software_id(self, software_id: uuid.UUID) -> int:
        stmt = delete(SoftwareAuction).where(SoftwareAuction.software_id == software_id)
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)

    async def list_by_status(self, status: AuctionStatus) -> Sequence[SoftwareAuction]:
        stmt = select(SoftwareAuction).where(SoftwareAuction.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_taken_down(self) -> Sequence[SoftwareAuction]:
        stmt = (
            select(SoftwareAuction)
            .where(SoftwareAuction.status == AuctionStatus.TAKEN_DOWN)
            .options(*_with_software())
            .order_by(SoftwareAuction.taken_down_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_active(self) -> Sequence[SoftwareAuction]:
        stmt = (
            select(SoftwareAuction)
            .where(
                SoftwareAuction.status.in_(
                    [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED],
                ),
                SoftwareAuction.approval_status == SoftwareAuctionApprovalStatus.APPROVED,
                SoftwareAuction.software.has(
                    and_(
                        Software.is_deleted.is_(False),
                        Software.taken_down.is_(False),
                        Software.status.is_(True),
                    ),
                ),
            )
            .options(*_with_software())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_expired(self, now: datetime) -> Sequence[SoftwareAuction]:
        stmt = select(SoftwareAuction).where(
            SoftwareAuction.status.in_([AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]),
            SoftwareAuction.end_time.isnot(None),
            SoftwareAuction.end_time < now,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_all_with_software(self) -> Sequence[SoftwareAuction]:
        stmt = select(SoftwareAuction).options(
            *_with_software(),
            selectinload(SoftwareAuction.bids),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_pending(self) -> Sequence[SoftwareAuction]:
        stmt = (
            select(SoftwareAuction)
            .where(
                SoftwareAuction.approval_status
                == SoftwareAuctionApprovalStatus.PENDING_APPROVAL,
            )
            .options(
                *_with_software(),
                selectinload(SoftwareAuction.bids),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_lister_user_id(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 200,
    ) -> Sequence[SoftwareAuction]:
        """Auctions for software listings owned by this user. Read-only."""
        stmt = (
            select(SoftwareAuction)
            .join(Software, Software.id == SoftwareAuction.software_id)
            .where(
                Software.listed_by_user_id == user_id,
                Software.is_deleted.is_(False),
            )
            .options(*_with_software())
            .order_by(SoftwareAuction.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_ids(
        self,
        auction_ids: Sequence[uuid.UUID],
    ) -> Sequence[SoftwareAuction]:
        if not auction_ids:
            return []
        stmt = (
            select(SoftwareAuction)
            .where(SoftwareAuction.id.in_(list(auction_ids)))
            .options(*_with_software())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()


class SoftwareAuctionBidRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, bid: SoftwareAuctionBid) -> SoftwareAuctionBid:
        self._session.add(bid)
        await self._session.flush()
        await self._session.refresh(bid)
        return bid

    async def save(self, bid: SoftwareAuctionBid) -> SoftwareAuctionBid:
        await self._session.flush()
        await self._session.refresh(bid)
        return bid

    async def list_by_auction(
        self,
        auction_id: uuid.UUID,
        *,
        desc: bool = True,
    ) -> Sequence[SoftwareAuctionBid]:
        stmt = select(SoftwareAuctionBid).where(
            SoftwareAuctionBid.software_auction_id == auction_id,
        )
        stmt = stmt.order_by(
            SoftwareAuctionBid.bid_time.desc() if desc else SoftwareAuctionBid.bid_time.asc(),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def clear_winning_flags(self, auction_id: uuid.UUID) -> None:
        bids = await self.list_by_auction(auction_id, desc=False)
        for bid in bids:
            bid.is_winning_bid = False
        await self._session.flush()

    async def list_by_bidder_id(
        self,
        bidder_id: uuid.UUID,
        *,
        limit: int = 500,
    ) -> Sequence[SoftwareAuctionBid]:
        """All bids placed by this user (newest first). Read-only."""
        stmt = (
            select(SoftwareAuctionBid)
            .where(SoftwareAuctionBid.bidder_id == bidder_id)
            .order_by(SoftwareAuctionBid.bid_time.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

"""
Async repository for the Bid entity.
"""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.auction.auction_entity import Auction
from app.entity.auction.bid_entity import Bid


def _alive_bid():
    return Bid.is_deleted.is_(False)


class BidRepository:
    """Data access for `bids` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_bid(self, bid: Bid) -> Bid:
        self._session.add(bid)
        await self._session.flush()
        await self._session.refresh(bid)
        return bid

    async def get_highest_bid(self, auction_id: uuid.UUID) -> Optional[Bid]:
        stmt = (
            select(Bid)
            .where(
                Bid.auction_id == auction_id,
                _alive_bid(),
            )
            .order_by(Bid.amount.desc(), Bid.created_at.asc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_bid_history(
        self,
        auction_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Bid]:
        stmt = (
            select(Bid)
            .where(Bid.auction_id == auction_id, _alive_bid())
            .order_by(Bid.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def increment_total_bids(self, auction_id: uuid.UUID) -> int:
        stmt = (
            update(Auction)
            .where(
                Auction.id == auction_id,
                Auction.is_deleted.is_(False),
            )
            .values(total_bids=Auction.total_bids + 1)
            .returning(Auction.total_bids)
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(stmt)
        new_total = result.scalar_one_or_none()
        if new_total is None:
            raise ValueError(f"Auction {auction_id} not found for bid increment.")
        return int(new_total)

    async def clear_winning_flag(self, auction_id: uuid.UUID) -> None:
        stmt = (
            update(Bid)
            .where(
                Bid.auction_id == auction_id,
                Bid.is_winning_bid.is_(True),
                _alive_bid(),
            )
            .values(is_winning_bid=False)
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(stmt)

    async def list_by_bidder_id(
        self,
        bidder_id: uuid.UUID,
        *,
        limit: int = 500,
    ) -> Sequence[Bid]:
        """All non-deleted bids placed by this user (newest first). Read-only."""
        stmt = (
            select(Bid)
            .where(Bid.bidder_id == bidder_id, _alive_bid())
            .order_by(Bid.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

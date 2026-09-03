"""Repository for generic auction participation-fee records."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.auction.auction_participation_entity import (
    AuctionParticipation,
    AuctionParticipationStatus,
    AuctionParticipationType,
)


class AuctionParticipationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, row: AuctionParticipation) -> AuctionParticipation:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(self, row: AuctionParticipation) -> AuctionParticipation:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_by_auction_and_user(
        self,
        auction_type: AuctionParticipationType,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[AuctionParticipation]:
        stmt = select(AuctionParticipation).where(
            AuctionParticipation.auction_type == auction_type,
            AuctionParticipation.auction_id == auction_id,
            AuctionParticipation.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_order_id(self, order_id: str) -> Optional[AuctionParticipation]:
        stmt = select(AuctionParticipation).where(
            AuctionParticipation.razorpay_order_id == order_id,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, participation_id: uuid.UUID) -> Optional[AuctionParticipation]:
        stmt = select(AuctionParticipation).where(AuctionParticipation.id == participation_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_by_user(self, user_id: uuid.UUID) -> list[AuctionParticipation]:
        stmt = (
            select(AuctionParticipation)
            .where(AuctionParticipation.user_id == user_id)
            .order_by(AuctionParticipation.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_completed(
        self,
        auction_type: AuctionParticipationType,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        row = await self.get_by_auction_and_user(auction_type, auction_id, user_id)
        return row is not None and row.status == AuctionParticipationStatus.COMPLETED

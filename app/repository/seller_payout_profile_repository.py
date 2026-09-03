"""Seller payout profile repository."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile


class SellerPayoutProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[SellerPayoutProfile]:
        stmt = select(SellerPayoutProfile).where(SellerPayoutProfile.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, profile: SellerPayoutProfile) -> SellerPayoutProfile:
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

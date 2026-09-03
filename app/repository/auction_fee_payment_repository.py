"""Data access for auction creation and bid fee payments."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.auction.auction_fee_payment_entity import (
    AuctionFeeAuctionType,
    AuctionFeePayment,
    AuctionFeePaymentKind,
    AuctionFeePaymentStatus,
)


class AuctionFeePaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, row: AuctionFeePayment) -> AuctionFeePayment:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(self, row: AuctionFeePayment) -> AuctionFeePayment:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_by_order_id(self, order_id: str) -> Optional[AuctionFeePayment]:
        stmt = select(AuctionFeePayment).where(
            AuctionFeePayment.razorpay_order_id == order_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_completed_creation_payment(
        self,
        *,
        order_id: str,
        user_id: uuid.UUID,
        auction_type: AuctionFeeAuctionType,
    ) -> Optional[AuctionFeePayment]:
        stmt = select(AuctionFeePayment).where(
            AuctionFeePayment.razorpay_order_id == order_id,
            AuctionFeePayment.user_id == user_id,
            AuctionFeePayment.payment_kind == AuctionFeePaymentKind.CREATION,
            AuctionFeePayment.auction_type == auction_type,
            AuctionFeePayment.status == AuctionFeePaymentStatus.COMPLETED,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_completed_bid_payment(
        self,
        *,
        order_id: str,
        user_id: uuid.UUID,
        auction_id: uuid.UUID,
        auction_type: AuctionFeeAuctionType,
    ) -> Optional[AuctionFeePayment]:
        stmt = select(AuctionFeePayment).where(
            AuctionFeePayment.razorpay_order_id == order_id,
            AuctionFeePayment.user_id == user_id,
            AuctionFeePayment.auction_id == auction_id,
            AuctionFeePayment.payment_kind == AuctionFeePaymentKind.BID,
            AuctionFeePayment.auction_type == auction_type,
            AuctionFeePayment.status == AuctionFeePaymentStatus.COMPLETED,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

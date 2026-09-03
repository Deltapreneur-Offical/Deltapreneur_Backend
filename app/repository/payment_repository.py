"""Async repository for domain-auction winner payments."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.auction.payment_entity import Payment
from app.utils.enums import PaymentStatus


def _alive_payment() -> Any:
    return Payment.is_deleted.is_(False)


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_order_id(self, razorpay_order_id: str) -> Optional[Payment]:
        stmt = select(Payment).where(
            Payment.razorpay_order_id == razorpay_order_id,
            _alive_payment(),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_success_for_auction(
        self,
        auction_id: uuid.UUID,
    ) -> Optional[Payment]:
        stmt = (
            select(Payment)
            .where(
                Payment.auction_id == auction_id,
                Payment.payment_status == PaymentStatus.SUCCESS,
                _alive_payment(),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_open_for_auction_user(
        self,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[Payment]:
        stmt = (
            select(Payment)
            .where(
                Payment.auction_id == auction_id,
                Payment.user_id == user_id,
                Payment.payment_status == PaymentStatus.PENDING,
                _alive_payment(),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, payment: Payment) -> Payment:
        self._session.add(payment)
        await self._session.flush()
        await self._session.refresh(payment)
        return payment

    async def save(self, payment: Payment) -> Payment:
        await self._session.flush()
        await self._session.refresh(payment)
        return payment

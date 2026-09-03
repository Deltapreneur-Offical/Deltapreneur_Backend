"""Venture deal transaction data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.coventure.venture_deal_event_entity import VentureDealEvent
from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction
from app.entity.coventure.venture_entity import Venture
from app.utils.venture_enums import VentureDealStatus


class VentureDealRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, txn: VentureDealTransaction) -> VentureDealTransaction:
        self._session.add(txn)
        await self._session.flush()
        await self._session.refresh(txn)
        return txn

    async def save(self, txn: VentureDealTransaction) -> VentureDealTransaction:
        await self._session.flush()
        await self._session.refresh(txn)
        return txn

    async def add_event(self, event: VentureDealEvent) -> VentureDealEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    def _deal_load_options(self):
        return (
            selectinload(VentureDealTransaction.buyer),
            selectinload(VentureDealTransaction.seller),
            selectinload(VentureDealTransaction.venture).selectinload(Venture.brand_details),
            selectinload(VentureDealTransaction.events),
            selectinload(VentureDealTransaction.pitch),
            selectinload(VentureDealTransaction.co_venture_application),
        )

    async def get_by_id(self, deal_id: uuid.UUID) -> Optional[VentureDealTransaction]:
        stmt = (
            select(VentureDealTransaction)
            .where(VentureDealTransaction.id == deal_id)
            .options(*self._deal_load_options())
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(
        self,
        deal_id: uuid.UUID,
    ) -> Optional[VentureDealTransaction]:
        stmt = (
            select(VentureDealTransaction)
            .where(VentureDealTransaction.id == deal_id)
            .with_for_update()
            .options(*self._deal_load_options())
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_razorpay_payment_id(
        self,
        razorpay_payment_id: str,
    ) -> Optional[VentureDealTransaction]:
        stmt = select(VentureDealTransaction).where(
            VentureDealTransaction.razorpay_payment_id == razorpay_payment_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[VentureDealTransaction]:
        stmt = (
            select(VentureDealTransaction)
            .where(
                (VentureDealTransaction.buyer_id == user_id)
                | (VentureDealTransaction.seller_id == user_id)
            )
            .options(
                selectinload(VentureDealTransaction.venture).selectinload(Venture.brand_details),
                selectinload(VentureDealTransaction.buyer),
                selectinload(VentureDealTransaction.seller),
                selectinload(VentureDealTransaction.events),
                selectinload(VentureDealTransaction.co_venture_application),
            )
            .order_by(VentureDealTransaction.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_open_for_venture(
        self,
        venture_id: uuid.UUID,
    ) -> Optional[VentureDealTransaction]:
        open_statuses = (
            VentureDealStatus.PENDING_ADMIN_APPROVAL,
            VentureDealStatus.PENDING_PAYMENT,
            VentureDealStatus.PAYMENT_HELD,
            VentureDealStatus.IN_PROGRESS,
        )
        stmt = (
            select(VentureDealTransaction)
            .where(
                VentureDealTransaction.venture_id == venture_id,
                VentureDealTransaction.deal_status.in_(open_statuses),
            )
            .order_by(VentureDealTransaction.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_open_for_venture_and_buyer(
        self,
        venture_id: uuid.UUID,
        buyer_id: uuid.UUID,
    ) -> Optional[VentureDealTransaction]:
        open_statuses = (
            VentureDealStatus.PENDING_ADMIN_APPROVAL,
            VentureDealStatus.PENDING_PAYMENT,
            VentureDealStatus.PAYMENT_HELD,
            VentureDealStatus.IN_PROGRESS,
        )
        stmt = (
            select(VentureDealTransaction)
            .where(
                VentureDealTransaction.venture_id == venture_id,
                VentureDealTransaction.buyer_id == buyer_id,
                VentureDealTransaction.deal_status.in_(open_statuses),
            )
            .order_by(VentureDealTransaction.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_co_venture_application(
        self,
        application_id: uuid.UUID,
    ) -> Optional[VentureDealTransaction]:
        stmt = (
            select(VentureDealTransaction)
            .where(VentureDealTransaction.co_venture_application_id == application_id)
            .order_by(VentureDealTransaction.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all_admin(self) -> Sequence[VentureDealTransaction]:
        stmt = (
            select(VentureDealTransaction)
            .options(
                selectinload(VentureDealTransaction.buyer),
                selectinload(VentureDealTransaction.seller),
                selectinload(VentureDealTransaction.venture).selectinload(Venture.brand_details),
                selectinload(VentureDealTransaction.events),
                selectinload(VentureDealTransaction.co_venture_application),
            )
            .order_by(VentureDealTransaction.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

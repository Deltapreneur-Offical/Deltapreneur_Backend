"""Domain marketplace transfer transaction repository."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.utils.transfer_enums import MarketplaceTransferStatus


class DomainMarketplaceTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tx: DomainMarketplaceTransaction) -> DomainMarketplaceTransaction:
        self._session.add(tx)
        await self._session.flush()
        await self._session.refresh(tx)
        return tx

    async def save(self, tx: DomainMarketplaceTransaction) -> DomainMarketplaceTransaction:
        await self._session.flush()
        await self._session.refresh(tx)
        return tx

    async def get_by_id(self, tx_id: uuid.UUID) -> Optional[DomainMarketplaceTransaction]:
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(DomainMarketplaceTransaction.id == tx_id)
            .options(
                selectinload(DomainMarketplaceTransaction.listing),
                selectinload(DomainMarketplaceTransaction.buyer),
                selectinload(DomainMarketplaceTransaction.seller),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, tx_id: uuid.UUID) -> Optional[DomainMarketplaceTransaction]:
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(DomainMarketplaceTransaction.id == tx_id)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_razorpay_payment_id(
        self, payment_id: str,
    ) -> Optional[DomainMarketplaceTransaction]:
        stmt = select(DomainMarketplaceTransaction).where(
            DomainMarketplaceTransaction.razorpay_payment_id == payment_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_listing_id(
        self, listing_id: uuid.UUID,
    ) -> Optional[DomainMarketplaceTransaction]:
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(DomainMarketplaceTransaction.domain_listing_id == listing_id)
            .order_by(DomainMarketplaceTransaction.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_seller(self, seller_id: uuid.UUID) -> Sequence[DomainMarketplaceTransaction]:
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(DomainMarketplaceTransaction.seller_id == seller_id)
            .options(selectinload(DomainMarketplaceTransaction.buyer))
            .order_by(DomainMarketplaceTransaction.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_buyer(self, buyer_id: uuid.UUID) -> Sequence[DomainMarketplaceTransaction]:
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(DomainMarketplaceTransaction.buyer_id == buyer_id)
            .options(selectinload(DomainMarketplaceTransaction.seller))
            .order_by(DomainMarketplaceTransaction.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_for_admin(
        self,
        *,
        transfer_status: Optional[MarketplaceTransferStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[DomainMarketplaceTransaction]:
        stmt = select(DomainMarketplaceTransaction).options(
            selectinload(DomainMarketplaceTransaction.buyer),
            selectinload(DomainMarketplaceTransaction.seller),
            selectinload(DomainMarketplaceTransaction.listing),
        )
        if transfer_status is not None:
            stmt = stmt.where(DomainMarketplaceTransaction.transfer_status == transfer_status)
        stmt = stmt.order_by(DomainMarketplaceTransaction.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_seller_deadline_candidates(
        self, now: datetime, *, limit: int = 50,
    ) -> Sequence[DomainMarketplaceTransaction]:
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(
                DomainMarketplaceTransaction.transfer_status == MarketplaceTransferStatus.AWAITING_AUTH_CODE,
                DomainMarketplaceTransaction.seller_deadline_at <= now,
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_reminder_candidates(
        self,
        now: datetime,
        *,
        hours_before: int,
        reminder_field: str,
        limit: int = 50,
    ) -> Sequence[DomainMarketplaceTransaction]:
        from datetime import timedelta

        window_start = now + timedelta(hours=hours_before)
        window_end = window_start + timedelta(hours=1)
        stmt = select(DomainMarketplaceTransaction).where(
            DomainMarketplaceTransaction.transfer_status == MarketplaceTransferStatus.AWAITING_AUTH_CODE,
            DomainMarketplaceTransaction.seller_deadline_at >= window_start,
            DomainMarketplaceTransaction.seller_deadline_at < window_end,
        ).limit(limit)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [r for r in rows if not getattr(r, reminder_field, False)]

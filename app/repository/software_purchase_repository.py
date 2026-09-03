"""Software purchase data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.utils.cocreation_enums import SoftwarePaymentStatus


class SoftwarePurchaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, purchase: SoftwarePurchase) -> SoftwarePurchase:
        self._session.add(purchase)
        await self._session.flush()
        await self._session.refresh(purchase)
        return purchase

    async def save(self, purchase: SoftwarePurchase) -> SoftwarePurchase:
        await self._session.flush()
        await self._session.refresh(purchase)
        return purchase

    async def get_by_id(self, purchase_id: uuid.UUID) -> Optional[SoftwarePurchase]:
        stmt = (
            select(SoftwarePurchase)
            .where(SoftwarePurchase.id == purchase_id)
            .options(selectinload(SoftwarePurchase.software))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, purchase_id: uuid.UUID) -> Optional[SoftwarePurchase]:
        stmt = (
            select(SoftwarePurchase)
            .where(SoftwarePurchase.id == purchase_id)
            .options(selectinload(SoftwarePurchase.software))
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_razorpay_order_id(self, order_id: str) -> Optional[SoftwarePurchase]:
        stmt = select(SoftwarePurchase).where(SoftwarePurchase.razorpay_order_id == order_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_razorpay_payment_id(self, payment_id: str) -> Optional[SoftwarePurchase]:
        stmt = select(SoftwarePurchase).where(SoftwarePurchase.razorpay_payment_id == payment_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_completed_for_buyer(
        self,
        software_id: uuid.UUID,
        buyer_id: uuid.UUID,
    ) -> Optional[SoftwarePurchase]:
        stmt = (
            select(SoftwarePurchase)
            .where(
                SoftwarePurchase.software_id == software_id,
                SoftwarePurchase.buyer_id == buyer_id,
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
            )
            .order_by(SoftwarePurchase.sold_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_completed_by_buyer(
        self,
        buyer_id: uuid.UUID,
    ) -> Sequence[SoftwarePurchase]:
        stmt = (
            select(SoftwarePurchase)
            .where(
                SoftwarePurchase.buyer_id == buyer_id,
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
            )
            .options(selectinload(SoftwarePurchase.software))
            .order_by(SoftwarePurchase.sold_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_latest_created(
        self,
        software_id: uuid.UUID,
        buyer_id: uuid.UUID,
    ) -> Optional[SoftwarePurchase]:
        stmt = (
            select(SoftwarePurchase)
            .where(
                SoftwarePurchase.software_id == software_id,
                SoftwarePurchase.buyer_id == buyer_id,
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.CREATED,
            )
            .order_by(SoftwarePurchase.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_completed_purchase(
        self,
        software_id: uuid.UUID,
        buyer_id: uuid.UUID,
    ) -> bool:
        stmt = select(SoftwarePurchase.id).where(
            SoftwarePurchase.software_id == software_id,
            SoftwarePurchase.buyer_id == buyer_id,
            SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def count_completed_for_software(self, software_id: uuid.UUID) -> int:
        stmt = select(func.count(SoftwarePurchase.id)).where(
            SoftwarePurchase.software_id == software_id,
            SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def count_completed_by_software_ids(
        self,
        software_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        if not software_ids:
            return {}
        stmt = (
            select(
                SoftwarePurchase.software_id,
                func.count(SoftwarePurchase.id),
            )
            .where(
                SoftwarePurchase.software_id.in_(software_ids),
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
            )
            .group_by(SoftwarePurchase.software_id)
        )
        result = await self._session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

    async def list_for_admin(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[SoftwarePurchase]:
        from app.entity.cocreation.software_entity import Software
        stmt = (
            select(SoftwarePurchase)
            .where(SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED)
            .options(
                selectinload(SoftwarePurchase.software),
                selectinload(SoftwarePurchase.buyer),
                selectinload(SoftwarePurchase.software).selectinload(Software.listed_by),
            )
            .order_by(SoftwarePurchase.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_completed_by_seller(
        self,
        seller_id: uuid.UUID,
    ) -> Sequence[SoftwarePurchase]:
        from app.entity.cocreation.software_entity import Software
        stmt = (
            select(SoftwarePurchase)
            .join(Software, SoftwarePurchase.software_id == Software.id)
            .where(
                Software.listed_by_user_id == seller_id,
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
            )
            .options(
                selectinload(SoftwarePurchase.software),
                selectinload(SoftwarePurchase.buyer),
            )
            .order_by(SoftwarePurchase.sold_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

"""Venture pitch data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.coventure.venture_entity import Venture
from app.entity.coventure.venture_pitch_entity import VenturePitch
from app.utils.venture_visibility import ACTIVE_ACQUISITION_STATUSES


def _with_details():
    return [
        selectinload(VenturePitch.buyer),
        selectinload(VenturePitch.venture).selectinload(Venture.brand_details),
        selectinload(VenturePitch.venture).selectinload(Venture.listed_by),
    ]


class VenturePitchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, pitch: VenturePitch) -> VenturePitch:
        self._session.add(pitch)
        await self._session.flush()
        await self._session.refresh(pitch)
        return pitch

    async def save(self, pitch: VenturePitch) -> VenturePitch:
        await self._session.flush()
        await self._session.refresh(pitch)
        return pitch

    async def get_by_id(self, pitch_id: uuid.UUID) -> Optional[VenturePitch]:
        stmt = (
            select(VenturePitch)
            .where(VenturePitch.id == pitch_id)
            .options(*_with_details())
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_for_venture(self, venture_id: uuid.UUID) -> Optional[VenturePitch]:
        stmt = (
            select(VenturePitch)
            .where(
                VenturePitch.venture_id == venture_id,
                VenturePitch.status.in_(ACTIVE_ACQUISITION_STATUSES),
            )
            .order_by(VenturePitch.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_applicant_user_id(
        self, venture_id: uuid.UUID,
    ) -> Optional[uuid.UUID]:
        row = await self.get_active_for_venture(venture_id)
        return row.buyer_user_id if row else None

    async def venture_ids_with_active_applications(self) -> set[uuid.UUID]:
        stmt = select(VenturePitch.venture_id).where(
            VenturePitch.status.in_(ACTIVE_ACQUISITION_STATUSES),
        )
        result = await self._session.execute(stmt)
        return {row[0] for row in result.all()}

    async def list_by_buyer(self, buyer_user_id: uuid.UUID) -> Sequence[VenturePitch]:
        stmt = (
            select(VenturePitch)
            .where(VenturePitch.buyer_user_id == buyer_user_id)
            .options(*_with_details())
            .order_by(VenturePitch.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_seller_ventures(
        self, seller_user_id: uuid.UUID,
    ) -> Sequence[VenturePitch]:
        stmt = (
            select(VenturePitch)
            .join(Venture, Venture.id == VenturePitch.venture_id)
            .where(Venture.listed_by_user_id == seller_user_id)
            .options(*_with_details())
            .order_by(VenturePitch.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_all_for_admin(self) -> Sequence[VenturePitch]:
        stmt = (
            select(VenturePitch)
            .options(*_with_details())
            .order_by(VenturePitch.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_venture_and_buyer(
        self,
        venture_id: uuid.UUID,
        buyer_user_id: uuid.UUID,
    ) -> Optional[VenturePitch]:
        stmt = select(VenturePitch).where(
            VenturePitch.venture_id == venture_id,
            VenturePitch.buyer_user_id == buyer_user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_venture(self, venture_id: uuid.UUID) -> Sequence[VenturePitch]:
        stmt = (
            select(VenturePitch)
            .where(VenturePitch.venture_id == venture_id)
            .order_by(VenturePitch.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_for_venture(self, venture_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(VenturePitch)
            .where(VenturePitch.venture_id == venture_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def count_by_venture_ids(
        self,
        venture_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        if not venture_ids:
            return {}
        stmt = (
            select(VenturePitch.venture_id, func.count())
            .where(VenturePitch.venture_id.in_(venture_ids))
            .group_by(VenturePitch.venture_id)
        )
        result = await self._session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}


VentureAcquisitionRepository = VenturePitchRepository

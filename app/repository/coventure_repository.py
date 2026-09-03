"""Co-venture application data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.coventure.partner_entity import CoVenture
from app.entity.coventure.venture_entity import Venture
from app.utils.venture_enums import CoVentureStatus


class CoVentureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, application: CoVenture) -> CoVenture:
        self._session.add(application)
        await self._session.flush()
        await self._session.refresh(application)
        return application

    async def save(self, application: CoVenture) -> CoVenture:
        await self._session.flush()
        await self._session.refresh(application)
        return application

    async def get_by_id(self, application_id: uuid.UUID) -> Optional[CoVenture]:
        stmt = (
            select(CoVenture)
            .where(CoVenture.id == application_id)
            .options(
                selectinload(CoVenture.venture).selectinload(Venture.brand_details),
                selectinload(CoVenture.venture).selectinload(Venture.listed_by),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists_for_venture_and_applicant(
        self,
        venture_id: uuid.UUID,
        applicant_id: uuid.UUID,
    ) -> bool:
        stmt = select(CoVenture.id).where(
            CoVenture.venture_id == venture_id,
            CoVenture.applicant_user_id == applicant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_by_venture_and_applicant(
        self,
        venture_id: uuid.UUID,
        applicant_id: uuid.UUID,
    ) -> Optional[CoVenture]:
        stmt = select(CoVenture).where(
            CoVenture.venture_id == venture_id,
            CoVenture.applicant_user_id == applicant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_applicant(self, applicant_id: uuid.UUID) -> Sequence[CoVenture]:
        stmt = (
            select(CoVenture)
            .where(CoVenture.applicant_user_id == applicant_id)
            .options(
                selectinload(CoVenture.venture).selectinload(Venture.brand_details),
            )
            .order_by(CoVenture.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_venture_owner(
        self,
        owner_id: uuid.UUID,
        *,
        status: Optional[CoVentureStatus] = None,
    ) -> Sequence[CoVenture]:
        stmt = (
            select(CoVenture)
            .join(Venture, CoVenture.venture_id == Venture.id)
            .where(Venture.listed_by_user_id == owner_id)
            .options(
                selectinload(CoVenture.venture).selectinload(Venture.brand_details),
                selectinload(CoVenture.applicant),
            )
            .order_by(CoVenture.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(CoVenture.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_selected_for_parties(
        self,
        user_id: uuid.UUID,
    ) -> Sequence[CoVenture]:
        """Selected partnership applications where user is owner or applicant."""
        stmt = (
            select(CoVenture)
            .join(Venture, CoVenture.venture_id == Venture.id)
            .where(
                CoVenture.status == CoVentureStatus.SELECTED,
                (
                    (CoVenture.applicant_user_id == user_id)
                    | (Venture.listed_by_user_id == user_id)
                ),
            )
            .options(
                selectinload(CoVenture.venture).selectinload(Venture.brand_details),
            )
            .order_by(CoVenture.updated_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

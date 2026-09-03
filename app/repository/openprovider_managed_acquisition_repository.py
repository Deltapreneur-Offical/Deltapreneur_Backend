"""Repository for OpenProvider managed acquisitions."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.domain.openprovider_managed_acquisition_entity import (
    OpenProviderManagedAcquisition,
)


class OpenProviderManagedAcquisitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _not_deleted():
        return or_(
            OpenProviderManagedAcquisition.is_deleted.is_(False),
            OpenProviderManagedAcquisition.is_deleted.is_(None),
        )

    async def create(
        self, row: OpenProviderManagedAcquisition
    ) -> OpenProviderManagedAcquisition:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(
        self, row: OpenProviderManagedAcquisition
    ) -> OpenProviderManagedAcquisition:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_by_id(
        self, acquisition_id: uuid.UUID
    ) -> Optional[OpenProviderManagedAcquisition]:
        stmt = select(OpenProviderManagedAcquisition).where(
            OpenProviderManagedAcquisition.id == acquisition_id,
            self._not_deleted(),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_all_admin(self) -> Sequence[OpenProviderManagedAcquisition]:
        stmt = (
            select(OpenProviderManagedAcquisition)
            .where(self._not_deleted())
            .order_by(OpenProviderManagedAcquisition.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_by_user(
        self, user_id: uuid.UUID
    ) -> Sequence[OpenProviderManagedAcquisition]:
        stmt = (
            select(OpenProviderManagedAcquisition)
            .where(
                OpenProviderManagedAcquisition.user_id == user_id,
                self._not_deleted(),
            )
            .order_by(OpenProviderManagedAcquisition.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

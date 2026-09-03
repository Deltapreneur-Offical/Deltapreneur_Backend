"""Domain transfer dispute repository."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.domain.domain_dispute_entity import DomainDispute, DomainDisputeEvidence


class DomainDisputeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, dispute: DomainDispute) -> DomainDispute:
        self._session.add(dispute)
        await self._session.flush()
        await self._session.refresh(dispute)
        return dispute

    async def save(self, dispute: DomainDispute) -> DomainDispute:
        await self._session.flush()
        await self._session.refresh(dispute)
        return dispute

    async def get_open_by_transaction(
        self, transaction_id: uuid.UUID,
    ) -> Optional[DomainDispute]:
        stmt = (
            select(DomainDispute)
            .where(
                DomainDispute.transaction_id == transaction_id,
                DomainDispute.status.in_(("OPEN", "UNDER_REVIEW")),
            )
            .options(selectinload(DomainDispute.evidence))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, dispute_id: uuid.UUID) -> Optional[DomainDispute]:
        stmt = (
            select(DomainDispute)
            .where(DomainDispute.id == dispute_id)
            .options(selectinload(DomainDispute.evidence))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_evidence(self, evidence: DomainDisputeEvidence) -> DomainDisputeEvidence:
        self._session.add(evidence)
        await self._session.flush()
        return evidence
